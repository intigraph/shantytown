"""Admission sees current membership; urgency bypasses only a proven full cap."""
from argparse import Namespace
import json
from subprocess import CompletedProcess

import pytest

from shantytown.answer import Answer
from shantytown.dispatch import Dispatcher, GovernorRefused
from shantytown.files import FilesRegistry, FilesTracker
from shantytown.plate_capacity import (
    CapacityUnknown, PlateFull, ensure_room, guard_producers, size,
)
from shantytown.producer_capacity import run
from shantytown.sd import SdTracker
from shantytown.tmux import NullPanes
from shantytown.work_item import command


def world(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path))
    tracker = FilesTracker(tmp_path / 'items')
    for i in range(10):
        tracker.create(f'Work {i}', assignee='worker', priority=2)
    return tracker


def assign(tracker, item, **changes):
    return command(Namespace(item=item.id, item_action='update', dry_run=False,
                             assignee='worker', status='in_progress', priority=None,
                             **changes), tracker)


def journal(tmp_path):
    path = tmp_path / '.local/state/shantytown/plate-capacity/overflow.jsonl'
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_refusal_names_members_and_real_repool_close_change_count(tmp_path, monkeypatch):
    tracker = world(tmp_path, monkeypatch)
    note = tracker.create('inbox: delivery', assignee='worker')
    pool = tracker.create('Ordinary work', priority=1)
    with pytest.raises(PlateFull) as failure:
        assign(tracker, pool)
    assert all(f'st-{n}' in str(failure.value) for n in range(1, 11))
    assert note.id not in str(failure.value)
    tracker.update(note.id, status='closed')
    assert size(tracker, 'worker') == 10
    tracker.update('st-1', assignee='')
    tracker.update('st-2', status='closed')
    assert size(tracker, 'worker') == 8
    assign(tracker, pool)
    assert size(tracker, 'worker') == 9 and journal(tmp_path) == []


def test_admission_never_reuses_frozen_crew_render(monkeypatch):
    rows = [dict(id=f'w{i}', title='Work', assignee='worker', status='open') for i in range(10)]
    tracker = SdTracker(quipu='https://example.test', prefix='fixture')
    tracker.render_shape_reads = object()
    tracker._roster_capacity = {'worker': Answer.complete_read(rows, how='frozen crew render')}
    monkeypatch.setattr(tracker, '_use_remote_projection', lambda: False)
    current = rows[3:]
    monkeypatch.setattr(tracker, '_owner_rows', lambda owner: Answer.complete_read(current, how='live'))
    assert size(tracker, 'worker') == 10  # Report keeps its consistent render snapshot.
    ensure_room(tracker, 'worker')       # Mutation must see seven.
    current[:] = rows
    with pytest.raises(PlateFull, match='w9'):
        ensure_room(tracker, 'worker')
    monkeypatch.setattr(tracker, '_owner_rows', lambda owner: Answer.capped([], how='live', caveat='lost'))
    with pytest.raises(CapacityUnknown, match='lost'):
        ensure_room(tracker, 'worker')


def test_p0_ownership_is_admitted_and_journal_is_not_a_commit_receipt(tmp_path, monkeypatch):
    tracker = world(tmp_path, monkeypatch)
    guard_producers(tracker, lambda *a: pytest.fail('urgent work must not be pooled'))
    urgent = tracker.create('Incident', priority=0)
    assign(tracker, urgent)
    assert tracker.get(urgent.id).assignee == 'worker' and size(tracker, 'worker') == 11
    events = journal(tmp_path)
    assert len(events) == 1  # Both command and producer guards examined this assignment.
    assert events[0]['item'] == urgent.id and events[0]['count'] == 10
    assert events[0]['counted_ids'] == sorted(f'st-{n}' for n in range(1, 11))
    assert events[0]['mutation_outcome'] == 'not_observed'
    assert (tmp_path / '.local/state/shantytown/plate-capacity/overflow.jsonl').stat().st_mode & 0o777 == 0o600


def test_p0_dry_run_and_blocker_priority_inheritance(tmp_path, monkeypatch):
    tracker = world(tmp_path, monkeypatch)
    crew = tmp_path / 'crew'
    crew.mkdir()
    (crew / 'worker.json').write_text(json.dumps({'pane': '%1'}))
    dispatcher = Dispatcher(FilesRegistry(crew), tracker, NullPanes())
    urgent = tracker.create('Incident', priority=0)
    dispatcher.go(urgent.id, 'worker', dry_run=True)
    assert tracker.get(urgent.id).assignee is None and journal(tmp_path) == []
    blocker = tracker.create('Required repair', priority=2)
    dispatcher.defer(urgent.id, 'bead', f'resume_when: closed:{blocker.id}',
                     dependency_reason='Incident requires the repair output')
    assert tracker.get(blocker.id).priority == 0
    assign(tracker, tracker.get(blocker.id))
    assert tracker.get(blocker.id).assignee == 'worker'
    assert journal(tmp_path)[0]['item'] == blocker.id


@pytest.mark.parametrize('priority', [None, True, 1, 2])
def test_no_label_or_unproven_priority_bypasses_cap(tmp_path, monkeypatch, priority):
    tracker = world(tmp_path, monkeypatch)
    pool = tracker.create('Work', priority=priority, labels=['blocks-p0'])
    with pytest.raises(PlateFull):
        assign(tracker, pool)
    assert tracker.get(pool.id).assignee is None and journal(tmp_path) == []


def test_journal_failure_and_unknown_membership_do_not_mutate(tmp_path, monkeypatch):
    tracker = world(tmp_path, monkeypatch)
    urgent = tracker.create('Incident', priority=0)
    folder = tmp_path / '.local/state/shantytown/plate-capacity'
    folder.mkdir(parents=True)
    (folder / 'overflow.jsonl').mkdir()
    with pytest.raises(CapacityUnknown, match='journal unavailable'):
        assign(tracker, urgent)
    assert tracker.get(urgent.id).assignee is None
    monkeypatch.setattr(tracker, 'capacity_rows', lambda owner: Answer.capped([], how='partial', caveat='lost'), raising=False)
    with pytest.raises(CapacityUnknown, match='lost'):
        assign(tracker, urgent)
    assert tracker.get(urgent.id).assignee is None


def test_sdk_priority_change_is_used_and_unknown_write_never_repeats(tmp_path, monkeypatch):
    tracker = world(tmp_path, monkeypatch)
    urgent = tracker.create('Reprioritized incident', priority=2)
    calls = []

    def execute(arguments):
        calls.append(arguments)
        tracker.update(urgent.id, assignee='worker', priority=0)
        raise TimeoutError('response lost after commit')

    with pytest.raises(TimeoutError):
        run(['update', urgent.id, '--assignee', 'worker', '--priority', '0'], tracker,
            execute, lambda *a: pytest.fail('no pooling'))
    assert len(calls) == 1 and tracker.get(urgent.id).assignee == 'worker'
    assert len(journal(tmp_path)) == 1


def test_automatic_p0_create_records_admission_without_pretending_id_known(tmp_path, monkeypatch):
    tracker = world(tmp_path, monkeypatch)
    guard_producers(tracker, lambda *a: pytest.fail('urgent work must not be pooled'))
    urgent = tracker.create('New incident', assignee='worker', priority=0)
    assert urgent.assignee == 'worker' and size(tracker, 'worker') == 11
    event = journal(tmp_path)[0]
    assert event['item'] is None and event['title'] == 'New incident'


def test_sdk_dry_run_writes_no_overflow_journal(tmp_path, monkeypatch):
    tracker = world(tmp_path, monkeypatch)
    urgent = tracker.create('Incident', priority=0)
    calls = []
    run(['update', urgent.id, '--assignee', 'worker', '--dry-run'], tracker,
        lambda args: calls.append(args) or CompletedProcess(args, 0, '{}', ''), lambda *a: None)
    assert len(calls) == 1 and '--dry-run' in calls[0]
    assert tracker.get(urgent.id).assignee is None and journal(tmp_path) == []


def test_p0_overflow_does_not_override_governor_or_claim_delivery(tmp_path, monkeypatch):
    tracker = world(tmp_path, monkeypatch)
    crew = tmp_path / 'crew'
    crew.mkdir()
    (crew / 'worker.json').write_text(json.dumps({'pane': '%1'}))
    urgent = tracker.create('Incident', priority=0)
    panes = NullPanes()
    dispatcher = Dispatcher(FilesRegistry(crew), tracker, panes,
                            governor=lambda item, agent: 'operator hold')
    with pytest.raises(GovernorRefused, match='operator hold'):
        dispatcher.go(urgent.id, 'worker')
    assert tracker.get(urgent.id).assignee is None and panes.sent == []
    assert journal(tmp_path)[0]['mutation_outcome'] == 'not_observed'


def test_incomplete_overflow_record_is_preserved_and_refuses_before_assignment(tmp_path, monkeypatch):
    tracker = world(tmp_path, monkeypatch)
    urgent = tracker.create('Incident', priority=0)
    path = tmp_path / '.local/state/shantytown/plate-capacity/overflow.jsonl'
    path.parent.mkdir(parents=True)
    path.write_bytes(b'{"event":')
    with pytest.raises(CapacityUnknown, match='incomplete overflow journal'):
        assign(tracker, urgent)
    assert path.read_bytes() == b'{"event":' and tracker.get(urgent.id).assignee is None
