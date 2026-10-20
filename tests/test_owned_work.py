"""Actual local lifecycle/outbox boundary, with no tmux or production store."""
from types import SimpleNamespace
import json

import pytest

from shantytown.answer import Answer, PartialAnswer
from shantytown.files import FilesRegistry
from shantytown.inbox import FilesInbox
from shantytown.owned_work import OwnedWork, LEASE


@pytest.fixture
def world(tmp_path):
    crew = tmp_path / 'crew'
    crew.mkdir()
    for name, card in {'worker': {'role': 'worker', 'reports_to': 'lead'},
                       'lead': {'role': 'lead', 'reports_to': 'admin'},
                       'admin': {'role': 'administrator'}}.items():
        (crew / (name + '.json')).write_text(json.dumps(card))
    reg = FilesRegistry(crew)
    box = FilesInbox(tmp_path / 'inbox')
    rows = [dict(id='first', title='first', assignee='worker', priority=1,
                 status='in_progress', due_at=None),
            dict(id='second', title='second', assignee='worker', priority=2,
                 status='open', due_at=None)]
    reads = []
    def read(name):
        reads.append(name)
        return Answer.complete_read(rows, how='complete synthetic owner scope')
    service = OwnedWork(tmp_path)
    def tick(at, **kw):
        return service.tick(reg, read, box, now=at, **kw)
    return SimpleNamespace(service=service, box=box, rows=rows, reads=reads,
                           tick=tick, reg=reg)


def test_grace_batches_both_seeds_once_and_preserves_ownership(world):
    world.service.stop('worker', at=100)
    assert world.tick(100) == []
    assert world.box.unread('lead') == []
    assert world.tick(399) == []
    assert world.reads == ['worker'], 'pending deadline is not an owner polling loop'
    assert world.tick(400) == [('worker', 'delivered')]
    messages = world.box.unread('lead')
    assert len(messages) == 1 and 'first P1' in messages[0].body and 'second P2' in messages[0].body
    assert [row['assignee'] for row in world.rows] == ['worker', 'worker']
    world.service.stop('worker', at=900)
    assert world.tick(1000) == []
    assert len(world.box.unread('lead')) == 1
    report = json.loads(next(path for path in world.service.root.glob('*.json')
                             if path.name != 'state.json').read_text())
    assert len(report['seeds']) == 2 and report['measured_at'] == 400
    assert report['native_expiry'].startswith('Unsupported:')


@pytest.mark.parametrize('urgent', ['p0', 'overdue'])
def test_urgent_is_immediate_and_batches_nonurgent(world, urgent):
    if urgent == 'p0':
        world.rows[0]['priority'] = 0
    else:
        # Offset lexical ordering must not hide an actual past instant.
        world.rows[0]['due_at'] = '1970-01-01T01:00:01+01:00'
    world.service.stop('worker', at=100)
    assert world.tick(100) == [('worker', 'delivered')]
    assert '2 seed(s)' in world.box.unread('lead')[0].body


def test_restart_before_grace_cancels_old_event(world):
    world.service.launch('worker', now=50)
    world.service.stop('worker', at=100)
    world.tick(100)
    world.service.launch('worker', now=200)
    assert world.tick(400) == []
    assert world.box.unread('lead') == []


def test_hook_cannot_resurrect_explicit_stop_or_ceiling(world):
    for ceiling in [False, True]:
        world.service.launch('worker', now=10)
        world.service.stop('worker', at=100, ceiling=ceiling)
        world.service.heartbeat('worker', now=200)
        assert world.service.snapshot()['worker']['state'] == ('ceiling' if ceiling else 'stopped')


def test_expiry_is_unknown_process_evidence_and_hook_cancels_grace(world):
    world.service.heartbeat('worker', now=100)
    assert world.tick(100 + LEASE - 1) == []
    assert world.tick(100 + LEASE) == []
    assert 'UNKNOWN' in world.service.snapshot()['worker']['reason']
    world.service.heartbeat('worker', now=100 + LEASE + 1)
    assert world.tick(100 + LEASE + 300) == []
    assert not world.box.unread('lead')


def test_expiry_replay_and_new_episode_identity(world):
    world.rows[0]['priority'] = 0
    world.service.heartbeat('worker', now=100)
    world.tick(100 + LEASE)
    assert len(world.box.unread('lead')) == 1
    world.tick(101 + LEASE)
    assert len(world.box.unread('lead')) == 1
    world.service.heartbeat('worker', now=102 + LEASE)
    world.tick(102 + 2 * LEASE)
    assert len(world.box.unread('lead')) == 2, 'a genuinely new lapse is a new episode'


def test_inbox_only_escalation_preserves_original_and_body(world):
    world.rows.clear()
    original = world.box.deliver('worker', 'private body stays with its recipient')
    world.service.stop('worker', at=100)
    world.tick(400)
    assert world.box.unread('worker')[0] == original
    notice = world.box.unread('lead')[0]
    assert '1 unread' in notice.body and 'private body' not in notice.body


def test_empty_scope_positive_control_cannot_include_foreign_or_closed(world):
    world.rows[:] = [dict(world.rows[0], assignee='other'),
                     dict(world.rows[1], status='closed')]
    world.service.stop('worker', at=100)
    world.tick(400)
    assert not world.box.unread('lead')
    world.rows.append(dict(id='new', assignee='worker', title='new', priority=0, status='open'))
    world.service.stop('worker', at=700, wake=True)
    world.tick(700)
    assert len(world.box.unread('lead')) == 1


def test_partial_owner_scope_is_not_no_work(world):
    world.service.stop('worker', at=100)
    with pytest.raises(PartialAnswer):
        world.service.tick(world.reg, lambda who: Answer.capped([], how='fixture', caveat='truncated'),
                           world.box, now=400)
    assert not world.box.unread('lead')
    assert world.service.snapshot()['worker']['notice'] == 'pending'
    world.tick(400)
    assert len(world.box.unread('lead')) == 1


@pytest.mark.parametrize('committed', [False, True])
def test_indeterminate_delivery_never_blindly_retries(world, committed):
    world.service.stop('worker', at=100)
    original = world.box.deliver
    attempts = []
    def uncertain(*args, **kwargs):
        attempts.append(True)
        if committed:
            original(*args, **kwargs)
        raise TimeoutError('unknown commit')
    world.box.deliver = uncertain
    with pytest.raises(TimeoutError):
        world.tick(400)
    world.tick(401)
    world.tick(402)
    assert len(attempts) == 1
    assert world.service.snapshot()['worker']['notice'] == ('delivered' if committed else 'unknown')
    if committed:
        # Acknowledgement cannot erase the recovery receipt.
        world.box.mark_read('lead')
        assert world.tick(403) == []


def test_orphan_routes_to_unambiguous_admin(world):
    (world.reg.root / 'worker.json').write_text(json.dumps({'role': 'worker', 'reports_to': 'missing'}))
    world.service.stop('worker', at=100)
    world.tick(400)
    assert len(world.box.unread('admin')) == 1


def test_long_queue_pointer_retains_full_uncapped_report(world):
    world.rows[:] = [dict(id=f'item-{n}', title='title', assignee='worker', priority=0,
                         status='open', due_at=None) for n in range(100)]
    world.service.stop('worker', at=100)
    world.tick(100)
    assert len(world.box.unread('lead')[0].body.encode()) <= 480
    report_path = world.service.snapshot()['worker']['report']
    assert len(json.loads(open(report_path).read())['seeds']) == 100


def test_snapshot_is_read_only_and_corrupt_state_is_loud(tmp_path):
    service = OwnedWork(tmp_path)
    assert service.snapshot() == {} and not service.root.exists()
    service.root.mkdir()
    (service.root / 'state.json').write_text('{')
    with pytest.raises(ValueError):
        service.heartbeat('worker', now=100)


@pytest.mark.parametrize('value', ['../escape', '', 'a/b'])
def test_agent_path_injection_refuses(tmp_path, value):
    with pytest.raises(ValueError):
        OwnedWork(tmp_path).stop(value, at=100)


def test_due_deadline_is_not_hidden_by_grace(world):
    world.rows[0]['due_at'] = '1970-01-01T00:01:50Z'
    world.service.stop('worker', at=100)
    world.tick(100)
    assert world.service.snapshot()['worker']['next_at'] == 110
    assert world.tick(110) == [('worker', 'delivered')]


def test_no_work_is_quiet_until_a_real_input_event(world):
    world.rows.clear()
    world.service.stop('worker', at=100)
    world.tick(400)
    world.tick(900)
    assert world.reads == ['worker']
    world.box.deliver('worker', 'input')
    world.service.stop('worker', at=900, wake=True)
    world.tick(900)
    assert len(world.box.unread('lead')) == 1


def test_lead_uses_normal_dispatch_after_notice(tmp_path):
    from shantytown.dispatch import Dispatcher
    from shantytown.files import FilesTracker, items
    from shantytown.tmux import NullPanes
    crew = tmp_path / 'crew'
    crew.mkdir()
    for name, card in {'worker': {'role': 'worker', 'reports_to': 'lead'},
                       'lead': {'role': 'lead'},
                       'receiver': {'role': 'worker', 'reports_to': 'lead', 'pane': '%5'}}.items():
        (crew / (name + '.json')).write_text(json.dumps(card))
    registry, tracker = FilesRegistry(crew), FilesTracker(tmp_path / 'items')
    first = tracker.create('first', assignee='worker', priority=0)
    second = tracker.create('second', assignee='worker', priority=1)
    box, service = FilesInbox(tmp_path / 'inbox'), OwnedWork(tmp_path)
    service.stop('worker', at=100)
    service.tick(registry, lambda name: Answer.complete_read(
        [vars(row) for row in items(tracker) if row.assignee == name], how='files owner'), box, now=100)
    assert len(box.unread('lead')) == 1
    assert tracker.get(first.id).assignee == tracker.get(second.id).assignee == 'worker'
    panes = NullPanes()
    Dispatcher(registry, tracker, panes, sender='lead').go(first.id, 'receiver', reassign=True)
    assert tracker.get(first.id).assignee == 'receiver'
    assert tracker.get(second.id).assignee == 'worker'
    assert len(panes.sent) == 1


def test_hook_capture_renews_lease_and_late_hook_preserves_stop(tmp_path, monkeypatch):
    from shantytown import stats
    monkeypatch.setenv('SHANTY_AGENT', 'worker')
    payload = dict(session_id='synthetic-session', hook_event_name='PostToolUse', tool_name='Read')
    stats.capture(tmp_path, payload)
    service = OwnedWork(tmp_path)
    assert service.snapshot()['worker']['state'] == 'live'
    service.stop('worker', at=100)
    stats.capture(tmp_path, payload)
    assert service.snapshot()['worker']['state'] == 'stopped'


def test_unknown_owner_does_not_starve_next_owner(tmp_path, monkeypatch, capsys):
    from shantytown import cli
    crew = tmp_path / 'crew'
    crew.mkdir()
    for name in ['first', 'second', 'lead']:
        (crew / (name + '.json')).write_text(json.dumps({'role': 'worker', 'reports_to': 'lead'}))
    service = OwnedWork(tmp_path)
    service.stop('first', at=100)
    service.stop('second', at=100)
    box = FilesInbox(tmp_path / 'inbox')
    def rows(name):
        if name == 'first':
            return Answer.capped([], how='fixture', caveat='unknown')
        return Answer.complete_read([dict(id='seed', title='seed', priority=0,
                                         assignee=name, status='open')], how='second owner')
    monkeypatch.setattr(cli, '_tracker', lambda args: SimpleNamespace(capacity_rows=rows))
    monkeypatch.setattr(cli, '_registry', lambda args: FilesRegistry(crew))
    monkeypatch.setattr(cli, '_inbox', lambda args: box)
    assert cli._owned_work_tick(SimpleNamespace(root=tmp_path)) == [('second', 'delivered')]
    assert 'first: UNKNOWN' in capsys.readouterr().err
    assert len(box.unread('lead')) == 1


def test_inbox_flag_keeps_durable_recipient_and_does_not_invent_stop(tmp_path, monkeypatch, capsys):
    from shantytown import cli
    from shantytown.protocols import Agent
    service = OwnedWork(tmp_path)
    service.heartbeat('worker', now=100)
    # A missing heartbeat is advisory evidence, not deliberate-stop intent.
    with service.locked() as data:
        data['worker'].update(state='expired', event='fixture', notice='pending', next_at=100)
    args = SimpleNamespace(root=tmp_path, message=['hello'], agent='worker',
                           dry_run=False, durable=True)
    card = Agent(name='worker', reports_to='lead')
    monkeypatch.setattr(cli, '_panes', lambda a: None)
    monkeypatch.setattr(cli, '_verified_sender', lambda a, p: ('lead', True))
    monkeypatch.setattr(cli, '_message_recipient', lambda a: card)
    nudges, destinations = [], []
    monkeypatch.setattr(cli, '_owned_work_tick', lambda a, **kw: nudges.append(kw))
    monkeypatch.setattr(cli, '_inbox_durable', lambda a, target, *args, **kw:
                        destinations.append(target.name) or 0)
    assert cli._cmd_inbox(args) == 0
    assert destinations == ['worker'] and nudges == [{'card': None, 'wake_owner': 'worker'}]
    assert 'expired' in capsys.readouterr().err
    assert service.snapshot()['worker']['state'] == 'expired'


def test_lost_write_return_is_not_delivery_and_never_retried(world):
    from shantytown.inbox import Message
    attempts = []
    def lost(to, body, frm=None):
        attempts.append(True)
        return Message(id='phantom', to=to, body=body)
    world.box.deliver = lost
    world.service.stop('worker', at=100)
    with pytest.raises(RuntimeError, match='read-back'):
        world.tick(400)
    world.tick(401)
    assert attempts == [True]
    assert world.service.snapshot()['worker']['notice'] == 'unknown'


def test_changed_receipt_does_not_prove_original_delivery(world):
    original = world.box.deliver
    def changed(to, body, frm=None):
        return original(to, body.split(' ', 1)[0] + ' altered', frm=frm)
    world.box.deliver = changed
    world.service.stop('worker', at=100)
    with pytest.raises(RuntimeError):
        world.tick(400)
    world.tick(401)
    assert world.service.snapshot()['worker']['notice'] == 'unknown'


def test_recovery_uses_original_lead_after_card_removed(world):
    original = world.box.deliver
    def uncertain(*args, **kwargs):
        original(*args, **kwargs)
        raise TimeoutError('committed but unknown')
    world.box.deliver = uncertain
    world.service.stop('worker', at=100)
    with pytest.raises(TimeoutError):
        world.tick(400)
    (world.reg.root / 'worker.json').unlink()
    assert world.tick(401) == [('worker', 'reconciled')]
    assert len(world.box.unread('lead')) == 1


@pytest.mark.parametrize('kind', ['stopped', 'ceiling', 'expired', 'legacy'])
def test_existing_ceiling_transfer_cannot_move_stopped_owned_work(tmp_path, monkeypatch, kind):
    from shantytown import cli, session_budget as sb, tend
    from shantytown.protocols import Agent, WorkItem
    from shantytown.stopped import FilesStops
    if kind == 'legacy':
        FilesStops(tmp_path / 'stopped').record('worker', 100)
    else:
        service = OwnedWork(tmp_path)
        service.stop('worker', at=100, ceiling=kind == 'ceiling')
        if kind == 'expired':
            with service.locked() as data:
                data['worker']['state'] = 'expired'
    limits = sb.Limits(max_items=4)
    spend = sb.Spend(session='fixture', items=4)
    monkeypatch.setattr(sb, 'gate', lambda root, name: (limits, spend,
                        sb.Ceiling('items', 4, 4, spend) if name == 'worker' else None))
    calls = []
    outcome = cli._ceiling_transfer_sweep(
        SimpleNamespace(root=tmp_path, dry_run=False),
        [Agent(name='worker', harness='codex'), Agent(name='receiver', harness='claude')],
        SimpleNamespace(findings=[tend.Finding('worker', 'up', 'ok')]),
        plate=lambda name: calls.append(name) or WorkItem(id='seed', assignee=name),
        gaming=SimpleNamespace(held=False), log=lambda message: None)
    assert outcome == [] and calls == [], 'must hold before a dispatch/ownership read'


def test_new_durable_mail_reopens_empty_ceiling_after_persist(tmp_path, monkeypatch):
    from shantytown import cli
    from shantytown.protocols import Agent
    crew = tmp_path / 'crew'
    crew.mkdir()
    for name, row in {'worker': {'role': 'worker', 'reports_to': 'lead'},
                      'lead': {'role': 'lead'}}.items():
        (crew / (name + '.json')).write_text(json.dumps(row))
    box, service = FilesInbox(tmp_path / 'inbox'), OwnedWork(tmp_path)
    service.stop('worker', at=100, ceiling=True)
    service.tick(FilesRegistry(crew), lambda name: Answer.complete_read([], how='empty'),
                 box, now=400)
    assert service.snapshot()['worker']['notice'] == 'empty'
    args = SimpleNamespace(root=tmp_path, message=['original body'], agent='worker',
                           dry_run=False, durable=True)
    monkeypatch.setattr(cli, '_panes', lambda a: None)
    monkeypatch.setattr(cli, '_verified_sender', lambda a, p: ('lead', True))
    monkeypatch.setattr(cli, '_message_recipient', lambda a: Agent(name='worker', reports_to='lead'))
    monkeypatch.setattr(cli, '_registry', lambda a: FilesRegistry(crew))
    monkeypatch.setattr(cli, '_tracker', lambda a: SimpleNamespace(
        capacity_rows=lambda name: Answer.complete_read([], how='empty')))
    monkeypatch.setattr(cli, '_inbox', lambda a: box)
    def persist(a, target, body, *args, **kw):
        box.deliver(target.name, body, frm='lead')
        return 0
    monkeypatch.setattr(cli, '_inbox_durable', persist)
    assert cli._cmd_inbox(args) == 0
    assert len(box.unread('worker')) == 1
    assert len(box.unread('lead')) == 1
    assert '1 unread' in box.unread('lead')[0].body
    assert service.snapshot()['worker']['state'] == 'ceiling'
