"""Human decisions stay owned/visible while executable work advances."""
import json
from types import SimpleNamespace

import pytest

from shantytown import feed_check, stop_event
from shantytown.dispatch import Blocked, Dispatcher
from shantytown.events import FilesEvents
from shantytown.files import FilesRegistry, FilesTracker
from shantytown.plate_capacity import real_work
from shantytown.protocols import Agent
from shantytown.tmux import NullPanes
from test_haul import _Reg, _Panes, _run, _haul_at


MARKERS = [
    {'labels': ['blocked:human']}, {'labels': ['desk']},
    {'labels': ['needs-stiwi']}, {'labels': ['decision-stiwi']},
    {'labels': ['decision-needed']}, {'title': '  ASK Stiwi: choose'},
    {'blocker_kind': 'blocked:human'},
]


def ask(**fields):
    return dict(id='fixture-ask', title='Choose a provider', assignee='billy',
                status='in_progress', priority=1, labels=[]) | fields


@pytest.mark.parametrize('marker', MARKERS)
def test_readers_skip_the_same_ask_as_capacity_without_mutating_it(marker):
    held = ask(**marker)
    work = dict(id='fixture-work', title='Repair the query', assignee='billy',
                status='open', priority=0)
    before = json.dumps(held, sort_keys=True)
    assert not real_work(held)
    assert stop_event._assigned_to('billy', [held, work]) == [work]
    assert feed_check.hauls([work], [held]) == {'billy': ['fixture-work']}
    assert feed_check.dispatchable(set(), [dict(held, assignee=None)]) == []
    assert json.dumps(held, sort_keys=True) == before


@pytest.mark.parametrize('harness', ['codex', 'claude'])
def test_active_ask_does_not_suppress_or_resume_instead_of_work(monkeypatch, capsys, harness):
    held = ask(labels=['blocked:human'])
    before = json.dumps(held, sort_keys=True)
    claims = []
    rc, block = _run(monkeypatch, capsys,
        reg=_Reg([Agent(name='billy', role='worker', pane='p-b', harness=harness)]),
        in_progress=[held], claims=claims,
        ready=[dict(id='fixture-work', title='Repair the query', assignee='billy', priority=0)])
    assert rc == 0 and block and 'HAUL:' in block['reason']
    assert 'fixture-work' in block['reason'] and 'fixture-ask' not in block['reason']
    assert claims == ['fixture-work']
    assert json.dumps(held, sort_keys=True) == before


@pytest.mark.parametrize('status', ['open', 'in_progress'])
def test_ask_only_plate_reports_once_to_lead_without_hook_or_claim(tmp_path, monkeypatch, capsys, status):
    held = ask(labels=['desk'], status=status)
    before = json.dumps(held, sort_keys=True)
    monkeypatch.setattr(feed_check, '_br_tracker', lambda *a: SimpleNamespace())
    monkeypatch.setattr(stop_event, 'route_stop', lambda *a, **k: SimpleNamespace(
        to='lead', reason=None, rose=False, detail=''))
    claims = []
    rows = {'ready': [held]} if status == 'open' else {'in_progress': [held]}
    events = FilesEvents(tmp_path / 'events')
    for attempt in range(2):
        rc, block = _haul_at(monkeypatch, capsys, tmp_path, claims=claims, **rows)
        assert rc == 0 and block is None
        assert claims == []
        if attempt == 0:
            pending = events.pending('lead')
            assert len(pending) == 1
            assert 'plate blocked on human' in pending[0].detail
            assert 'fixture-ask' in pending[0].detail
            events.drain('lead')
    assert events.pending('lead') == [], 'unchanged ASK must not repeatedly wake the lead'
    assert json.dumps(held, sort_keys=True) == before


@pytest.mark.parametrize('marker', [m for m in MARKERS if 'blocker_kind' not in m])
@pytest.mark.parametrize('dry_run', [False, True])
def test_go_refuses_ask_before_any_item_change_or_send(tmp_path, marker, dry_run):
    crew = tmp_path / 'crew'
    crew.mkdir()
    (crew / 'billy.json').write_text(json.dumps({'role': 'worker', 'pane': '%1'}))
    tracker = FilesTracker(tmp_path / 'items')
    fields = dict(title='Choose a provider', labels=[]) | marker
    item = tracker.create(fields.pop('title'), assignee='billy', **fields)
    before = tracker._path(item.id).read_bytes()
    panes = NullPanes()
    with pytest.raises(Blocked, match='human'):
        Dispatcher(FilesRegistry(crew), tracker, panes).go(item.id, 'billy', dry_run=dry_run)
    assert tracker._path(item.id).read_bytes() == before
    assert panes.sent == []


def test_ordinary_work_mentioning_ask_or_desk_stays_eligible():
    item = ask(title='Document ASK Stiwi and desk syntax', labels=['desk-notes'])
    assert real_work(item)
    assert stop_event._assigned_to('billy', [item]) == [item]
    assert feed_check.hauls([], [item]) == {'billy': ['fixture-ask']}
    assert feed_check.dispatchable(set(), [dict(item, assignee=None)]) == [
        ('fixture-ask', item['title'])]
