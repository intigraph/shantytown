"""A hard cap applies to urgent assignments across every cooperating producer."""
from argparse import Namespace
import json
from subprocess import CompletedProcess

import pytest

from shantytown.answer import Answer
from shantytown.dispatch import Dispatcher
from shantytown.files import FilesRegistry, FilesTracker
from shantytown.plate_capacity import CapacityUnknown, PlateFull, ensure_room, guard_producers, size
from shantytown.producer_capacity import run
from shantytown.sd import SdTracker
from shantytown.tmux import NullPanes
from shantytown.work_item import command


def world(tmp_path, monkeypatch, count=10):
    monkeypatch.setenv('HOME', str(tmp_path))
    tracker = FilesTracker(tmp_path / 'items')
    for i in range(count):
        tracker.create(f'Work {i}', assignee='worker', priority=2)
    return tracker


def assign(tracker, item):
    return command(Namespace(item=item.id, item_action='update', dry_run=False,
                             assignee='worker', status='in_progress', priority=None), tracker)


def test_refusal_names_members_and_repooling_frees_a_slot(tmp_path, monkeypatch):
    tracker = world(tmp_path, monkeypatch)
    note = tracker.create('inbox: delivery', assignee='worker')
    pool = tracker.create('Incident', priority=0)
    with pytest.raises(PlateFull) as failure:
        assign(tracker, pool)
    assert all(f'st-{n}' in str(failure.value) for n in range(1, 11))
    assert note.id not in str(failure.value)
    tracker.update(note.id, status='closed')
    assert size(tracker, 'worker') == 10
    tracker.update('st-1', assignee='')
    assign(tracker, pool)
    assert size(tracker, 'worker') == 10 and tracker.get(pool.id).assignee == 'worker'


def test_admission_never_reuses_frozen_crew_render(monkeypatch):
    rows = [dict(id=f'w{i}', title='Work', assignee='worker', status='open') for i in range(10)]
    tracker = SdTracker(quipu='https://example.test', prefix='fixture')
    tracker.render_shape_reads = object()
    tracker._roster_capacity = {'worker': Answer.complete_read(rows, how='frozen crew render')}
    monkeypatch.setattr(tracker, '_use_remote_projection', lambda: False)
    current = rows[3:]
    monkeypatch.setattr(tracker, '_owner_rows', lambda owner: Answer.complete_read(current, how='live'))
    assert size(tracker, 'worker') == 10
    ensure_room(tracker, 'worker', candidate={'title': 'Incident', 'priority': 0})
    current[:] = rows
    with pytest.raises(PlateFull, match='w9'):
        ensure_room(tracker, 'worker', candidate={'title': 'Incident', 'priority': 0})
    monkeypatch.setattr(tracker, '_owner_rows', lambda owner: Answer.capped([], how='live', caveat='lost'))
    with pytest.raises(CapacityUnknown, match='lost'):
        ensure_room(tracker, 'worker', candidate={'title': 'Incident', 'priority': 0})


@pytest.mark.parametrize('dry_run', [False, True])
def test_p0_dispatch_at_ten_makes_no_send_or_assignment(tmp_path, monkeypatch, dry_run):
    tracker = world(tmp_path, monkeypatch)
    crew = tmp_path / 'crew'
    crew.mkdir()
    (crew / 'worker.json').write_text(json.dumps({'pane': '%1'}))
    panes = NullPanes()
    dispatcher = Dispatcher(FilesRegistry(crew), tracker, panes)
    urgent = tracker.create('Incident', priority=0)
    with pytest.raises(PlateFull):
        dispatcher.go(urgent.id, 'worker', dry_run=dry_run)
    assert tracker.get(urgent.id).assignee is None and panes.sent == []


def test_inherited_p0_requires_a_slot_and_existing_owner_can_resume(tmp_path, monkeypatch):
    tracker = world(tmp_path, monkeypatch)
    crew = tmp_path / 'crew'
    crew.mkdir()
    (crew / 'worker.json').write_text(json.dumps({'pane': '%1'}))
    dispatcher = Dispatcher(FilesRegistry(crew), tracker, NullPanes())
    urgent = tracker.create('Incident', priority=0)
    blocker = tracker.create('Required repair', priority=2)
    dispatcher.defer(urgent.id, 'bead', f'resume_when: closed:{blocker.id}',
                     dependency_reason='Incident requires the repair output')
    assert tracker.get(blocker.id).priority == 0
    with pytest.raises(PlateFull):
        assign(tracker, tracker.get(blocker.id))
    # Updating an existing held P0 consumes no additional slot.
    tracker.update('st-1', priority=0)
    assign(tracker, tracker.get('st-1'))
    assert size(tracker, 'worker') == 10


def test_automatic_p0_create_stays_in_pool_and_preserves_old_journal(tmp_path, monkeypatch):
    tracker = world(tmp_path, monkeypatch)
    path = tmp_path / '.local/state/shantytown/plate-capacity/overflow.jsonl'
    path.parent.mkdir(parents=True)
    path.write_bytes(b'{"event":')
    before = path.stat()
    notices = []
    guard_producers(tracker, lambda *a: notices.append(a))
    urgent = tracker.create('Incident', assignee='worker', priority=0)
    assert urgent.assignee is None and size(tracker, 'worker') == 10
    assert notices == [('worker', urgent.id)]
    after = path.stat()
    assert path.read_bytes() == b'{"event":'
    assert (before.st_ino, before.st_mtime_ns) == (after.st_ino, after.st_mtime_ns)


@pytest.mark.parametrize('priority', ['0', 'P0', 'p0', 'P+0000', ' +00 '])
def test_sdk_priority_spellings_cannot_bypass_cap(tmp_path, monkeypatch, priority):
    tracker = world(tmp_path, monkeypatch)
    arguments = ['create', 'Incident', '--assignee', 'worker', '--priority', priority]
    calls, notices = [], []
    def execute(argv):
        calls.append(argv)
        assert '--assignee' not in argv
        item = tracker.create('Incident', priority=0)
        return CompletedProcess(argv, 0, json.dumps({'id': item.id}), '')
    run(arguments, tracker, execute, lambda *a: notices.append(a))
    assert len(calls) == 1 and len(notices) == 1 and size(tracker, 'worker') == 10


@pytest.mark.parametrize('flags', [
    ['--acceptance-criteria', '--dry-run'], ['--acceptance-criteria=--dry-run'],
    ['--description', '--dry-run'], ['-d--dry-run'],
])
def test_sdk_literal_dry_run_value_cannot_skip_capacity(tmp_path, monkeypatch, flags):
    tracker = world(tmp_path, monkeypatch)
    item = tracker.create('Incident', assignee='worker', status='deferred', priority=0)
    before = tracker._path(item.id).read_bytes()
    with pytest.raises(PlateFull):
        run(['update', item.id, '--status', 'in_progress', *flags], tracker,
            lambda argv: pytest.fail('full reactivation must not reach SDK'), lambda *a: None)
    assert tracker._path(item.id).read_bytes() == before


def test_sdk_allowed_unknown_commit_is_not_retried(tmp_path, monkeypatch):
    tracker = world(tmp_path, monkeypatch, count=9)
    urgent = tracker.create('Incident', priority=0)
    calls = []
    def execute(argv):
        calls.append(argv)
        tracker.update(urgent.id, assignee='worker')
        raise TimeoutError('response lost after commit')
    with pytest.raises(TimeoutError):
        run(['update', urgent.id, '--assignee', 'worker'], tracker, execute, lambda *a: None)
    assert len(calls) == 1 and size(tracker, 'worker') == 10


@pytest.mark.parametrize('priority', ['P2', 'p2', '0002', ' +02 ', '\t p4 \n'])
def test_sdk_valid_priority_preserves_original_argv_below_cap(tmp_path, monkeypatch, priority):
    tracker = world(tmp_path, monkeypatch, count=9)
    arguments = ['create', 'Work', '--assignee', 'worker', '--priority', priority]
    calls = []
    run(arguments, tracker,
        lambda argv: calls.append(argv) or CompletedProcess(argv, 0, '{}', ''),
        lambda *a: pytest.fail('below cap'))
    assert calls == [arguments]


@pytest.mark.parametrize('priority', ['', 'P', 'Pp0', '5', 'P5', '-0', 'P-1', '++0', '１', '1.0'])
def test_sdk_invalid_priority_refuses_before_transport(tmp_path, monkeypatch, priority):
    tracker = world(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='unsupported producer priority'):
        run(['create', 'Incident', '--assignee', 'worker', '--priority', priority], tracker,
            lambda argv: pytest.fail('invalid priority must not reach SDK'), lambda *a: None)
