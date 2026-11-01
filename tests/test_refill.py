"""Natural refill selects work; normal dispatch retains every write gate."""
import json
from types import SimpleNamespace as NS
import pytest
from shantytown import feed_check
from shantytown.refill import Refiller, ordered, from_cli, metrics
from shantytown.answer import Answer
from shantytown.triage import Action


def row(ident, **kw):
    return dict(id=ident, title=ident, priority=1, status='open', labels=[]) | kw


def feeder(tmp_path, monkeypatch, rows, *, active=(), free=('a', 'b'), preview=None, dispatch=None):
    monkeypatch.setattr(feed_check, 'free_feedable_workers', lambda *a, **k: list(free))
    monkeypatch.setattr(feed_check, 'haul_hold_reason', lambda *a: '')
    calls = []
    def send(item, worker):
        calls.append((item, worker))
        return 0
    f = Refiller(tmp_path, None, None, None, snapshot=lambda: (rows, list(active)),
                 preview=preview or (lambda *a: True), dispatch=dispatch or send,
                 log=lambda *a: None, clock=lambda: 1000)
    return f, calls


def test_empty_and_blocked_plates_are_refilled_without_admin_message(tmp_path, monkeypatch):
    rows = [row('first'), row('second')]
    blocked = row('blocked', assignee='a', labels=['blocked:external'])
    f, calls = feeder(tmp_path, monkeypatch, rows, active=[blocked])
    assert f.sweep() == ['a', 'b']
    assert calls == [('first', 'a'), ('second', 'b')]


def test_existing_ready_or_active_work_is_haul_not_a_competing_dispatch(tmp_path, monkeypatch):
    f, calls = feeder(tmp_path, monkeypatch, [row('owned', assignee='a'), row('new')],
                      active=[row('running', assignee='b')])
    assert f.sweep() == [] and not calls


def test_order_and_structured_gates_do_not_invent_ready_work():
    candidates = [row('later'), row('urgent', priority=0),
                  row('blocked', labels=['blocked:external']),
                  row('human', title='ASK Stiwi: choose'),
                  row('owned', assignee='other'), row('parked', labels=['parked:gate']),
                  row('deferred', defer_until='2099-01-01'), row('epic', issue_type='epic')]
    assert [r['id'] for r in ordered(candidates)] == ['urgent', 'later']


def test_per_worker_preview_can_skip_ineligible_review_without_starving_authoring(tmp_path, monkeypatch):
    f, calls = feeder(tmp_path, monkeypatch, [row('review'), row('author')],
        free=['claude'], preview=lambda item, worker: item != 'review')
    assert f.sweep() == ['claude'] and calls == [('author', 'claude')]


def test_hold_is_rechecked_before_any_dispatch(tmp_path, monkeypatch):
    f, calls = feeder(tmp_path, monkeypatch, [row('new')])
    monkeypatch.setattr(feed_check, 'haul_hold_reason', lambda *a: 'gaming')
    assert f.sweep() == [] and not calls


def test_indeterminate_send_reserves_both_worker_and_item_across_ticks(tmp_path, monkeypatch):
    calls = []
    def uncertain(item, worker):
        calls.append((item, worker))
        raise TimeoutError('could already be delivered')
    f, _ = feeder(tmp_path, monkeypatch, [row('new')], dispatch=uncertain)
    assert f.sweep() == []
    assert f.sweep() == []
    assert calls == [('new', 'a')]
    state = json.loads((tmp_path / 'refill/state.json').read_text())
    assert state['pending']['a']['item'] == 'new'


def test_failed_snapshot_is_not_an_empty_plate_or_permission_to_dispatch(tmp_path, monkeypatch):
    f, calls = feeder(tmp_path, monkeypatch, [row('new')])
    f.snapshot = lambda: (_ for _ in ()).throw(TimeoutError())
    assert f.sweep() == [] and not calls


def test_fresh_dispatch_refusal_does_not_send_a_second_item_to_same_worker(tmp_path, monkeypatch):
    calls = []
    f, _ = feeder(tmp_path, monkeypatch, [row('one'), row('two')], free=['a'],
                  dispatch=lambda i, w: (calls.append((i, w)) or 1))
    assert f.sweep() == [] and calls == [('one', 'a')]
    assert json.loads((tmp_path / 'refill/state.json').read_text())['pending'] == {}


@pytest.mark.parametrize('remote_owned,peer_error', [(False, False), (True, False), (False, True)])
def test_cli_adapter_reads_observed_owners_and_uses_normal_dispatch(tmp_path, monkeypatch,
                                                                  remote_owned, peer_error):
    from shantytown import cli, fleet, refill
    reg = NS(all=lambda: Answer.complete_read([NS(name='local')], how='fixture'))
    monkeypatch.setattr(feed_check, 'free_feedable_workers', lambda *a, **kw: ['local'])
    monkeypatch.setattr(feed_check, 'haul_hold_reason', lambda *a: '')
    monkeypatch.setattr(fleet, 'collect', lambda peers: [dict(host='peer',
        error='unavailable' if peer_error else None, agents=[] if peer_error else [
            dict(name='remote', live=True, work='idle', state='up', role='worker')])])
    owners_read = []
    def ready(root, registry, owners):
        owners_read.append(set(owners))
        return [row('one'), row('two')]
    def active(root, registry, *, owners):
        owners_read.append(set(owners))
        return [row('owned', assignee='remote', status='in_progress')] if remote_owned else []
    monkeypatch.setattr(feed_check, 'tend_ready', ready)
    monkeypatch.setattr(feed_check, 'tend_active', active)
    monkeypatch.setattr(cli, '_tracker', lambda a: NS(get=lambda ident:
        NS(id=ident, status='open', assignee='', defer_until=None, labels=[])))
    monkeypatch.setattr(cli, '_wire', lambda a: NS(triage=lambda *args: NS(action=Action.NUDGE)))
    calls = []
    def go(args):
        calls.append((args.item, args.agent, args.dry_run))
        assert not args.reassign and not args.quipu_node and args.no_graph_context
        return 0
    monkeypatch.setattr(cli, '_cmd_go', go)
    monkeypatch.setattr(refill, 'report', lambda *a, **kw: None)
    result = from_cli(NS(root=tmp_path), reg, None, None, NS(host_peers={}), log=lambda *a: None)
    expected_owners = {'local'} if peer_error else {'local', 'remote'}
    assert owners_read == [expected_owners, expected_owners]
    assert calls[0] == ('one', 'local', False)
    if remote_owned or peer_error:
        assert result == ['local'] and len(calls) == 1
    else:
        assert result == ['local', 'remote']
        assert calls[1:] == [('two', 'remote', True), ('two', 'remote', False)]
    state = json.loads((tmp_path / 'refill/state.json').read_text())
    assert state['coverage'] is not peer_error


def test_metrics_preserve_unknown_and_distinguish_owned_queue_from_eligibility(tmp_path, monkeypatch):
    f, calls = feeder(tmp_path, monkeypatch, [row('owned', assignee='a')], free=['a'])
    f.sweep()
    f.clock = lambda: 2000
    f.sweep()
    output = metrics(tmp_path, 2000)
    assert 'st_refill_owned_queue_idle_seconds 1000' in output
    assert 'st_refill_idle_eligible_seconds' not in output
    assert 'st_refill_observation_known 1' in output
    assert 'st_refill_observation_known 0' in metrics(tmp_path, 3000)
    f.snapshot = lambda: (_ for _ in ()).throw(TimeoutError())
    f.sweep()
    assert 'st_refill_observation_known 0' in metrics(tmp_path, 2000)


def test_regression_alert_uses_existing_changed_digest_path(tmp_path, monkeypatch):
    from shantytown import creel_advisory, refill
    reports = []
    class Alerter:
        def __init__(self, *a, **kw):
            assert kw['filename'] == 'auto_refill.json'
        def sweep(self, advice):
            reports.append(advice['fleet'])
    monkeypatch.setattr(creel_advisory, 'Alerter', Alerter)
    f, calls = feeder(tmp_path, monkeypatch, [row('new')], free=['a'],
        preview=lambda *a: (_ for _ in ()).throw(TimeoutError()))
    f.sweep()
    refill.report(tmp_path, None, None)
    assert reports[-1].failure and reports[-1].key == 'a'
    assert 'st_refill_observation_known 0' in metrics(tmp_path, 1000)
    f.preview = lambda *a: True
    f.sweep()
    refill.report(tmp_path, None, None)
    assert not reports[-1].failure and reports[-1].key == 'clear'


def test_slow_complete_snapshot_cannot_consume_the_dispatch_selection_budget(tmp_path, monkeypatch):
    from shantytown import refill
    now = [0]
    monkeypatch.setattr(refill.time, 'monotonic', lambda: now[0])
    f, calls = feeder(tmp_path, monkeypatch, [row('new')], free=['a'])
    def snapshot():
        now[0] += 60
        return [row('new')], []
    f.snapshot = snapshot
    assert f.sweep() == ['a'] and calls == [('new', 'a')]


def test_slow_unknown_worker_does_not_starve_next_member_on_next_tick(tmp_path, monkeypatch):
    from shantytown import refill
    now = [0]
    monkeypatch.setattr(refill.time, 'monotonic', lambda: now[0])
    def preview(item, worker):
        if worker == 'a':
            now[0] += 60
            raise TimeoutError()
        return True
    f, calls = feeder(tmp_path, monkeypatch, [row('new')], preview=preview)
    assert f.sweep() == [] and not calls
    assert f.sweep() == ['b'] and calls == [('new', 'b')]


def test_held_owned_queue_is_not_reported_as_a_late_idle_queue(tmp_path, monkeypatch):
    f, calls = feeder(tmp_path, monkeypatch, [row('owned', assignee='a')], free=['a'])
    monkeypatch.setattr(feed_check, 'haul_hold_reason', lambda *a: 'media')
    f.sweep()
    f.clock = lambda: 3000
    f.sweep()
    state = json.loads((tmp_path / 'refill/state.json').read_text())
    assert state['waiting'] == {} and state['observations']['a']['state'] == 'held'
    assert not calls
