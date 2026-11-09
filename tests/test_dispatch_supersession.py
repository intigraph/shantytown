"""Superseded native CAS attempts retain evidence without blocking fresh work."""
import pytest

from shantytown import cli
from shantytown.dispatch import DispatchedButUntracked
from shantytown.dispatch_receipts import ReceiptConflict, assignment_supersession
from shantytown.protocols import SubmissionObserved
from test_dispatch_binding import world, snapshot


def interrupted(world, monkeypatch):
    root, dispatcher, binding, tracker, panes = world
    claim = binding.assignments.claim
    def stop(row, updates):
        claim(row, updates)
        raise KeyboardInterrupt()
    monkeypatch.setattr(binding.assignments, 'claim', stop)
    with pytest.raises(KeyboardInterrupt):
        dispatcher.go('work-1', 'worker')
    monkeypatch.setattr(binding.assignments, 'claim', claim)
    return binding.store.pending('work-1')


def test_newer_native_release_allows_fresh_dispatch_without_replaying_old_claim(world, monkeypatch):
    root, dispatcher, binding, tracker, panes = world
    old = interrupted(world, monkeypatch)
    tracker.update('work-1', status='open', assignee='')
    released = tracker.get('work-1').revision
    with pytest.raises(ReceiptConflict):
        dispatcher.go('work-1', 'worker')
    result = binding.supersede(old['id'])
    assert result['state'] == 'superseded' and not result['execution_authorized']
    new = dispatcher.go('work-1', 'worker')
    assert new.receipt_id != old['id'] and not new.replayed
    assert len(panes.sent) == 2
    assert binding.reconcile(new.receipt_id)['execution_authorized']
    assert not binding.reconcile(old['id'])['execution_authorized']
    retired = binding.store.read(old['id'])
    assert retired['state'] == 'superseded'
    assert retired['supersession']['revision'] == released
    for key in ('text', 'body_sha256', 'submission', 'revision', 'request'):
        assert retired[key] == old[key]
    before = snapshot(root)
    with pytest.raises(ReceiptConflict):
        binding.store.assign(old['id'], old, lambda _: pytest.fail('old claim retried'))
    with pytest.raises(ReceiptConflict):
        binding.store.submitted(old['id'], SubmissionObserved(old['pane'], old['body_sha256']))
    with pytest.raises(ReceiptConflict):
        binding.store.recover_assignment(old['id'], dict(receipt=old['id'], revision=released))
    with pytest.raises(ReceiptConflict):
        binding.store.prepare(old, old['text'])
    assert snapshot(root) == before


@pytest.mark.parametrize('change', ['owner', 'status', 'read-unknown'])
def test_unproven_or_not_released_native_state_cannot_retire_unknown_attempt(world, monkeypatch, change):
    root, dispatcher, binding, tracker, panes = world
    old = interrupted(world, monkeypatch)
    if change == 'owner':
        tracker.update('work-1', status='open', assignee='worker')
    elif change == 'status':
        tracker.update('work-1', status='in_progress', assignee='')
    else:
        tracker.update('work-1', status='open', assignee='')
        monkeypatch.setattr(binding.assignments, 'read', lambda _: (_ for _ in ()).throw(OSError('read failed')))
        monkeypatch.setattr(binding.assignments, 'supersession', lambda _: (_ for _ in ()).throw(OSError('read failed')), raising=False)
    with pytest.raises((ReceiptConflict, DispatchedButUntracked)):
        dispatcher.go('work-1', 'worker')
    with pytest.raises((ReceiptConflict, OSError)):
        binding.supersede(old['id'])
    assert binding.store.read(old['id'])['state'] == 'assigning'
    assert len(panes.sent) == 1


@pytest.mark.parametrize('change', [dict(id='other'), dict(revision=1),
    dict(revision=True), dict(status='in_progress'), dict(assignee='other'),
    dict(defer_until='2099-01-01T00:00:00Z')])
def test_supersession_requires_exact_newer_undeferred_native_release(change):
    receipt = dict(id='a' * 32, item='work-1', revision=1)
    current = dict(id='work-1', revision=2, status='open', assignee=None)
    with pytest.raises(ReceiptConflict):
        assignment_supersession(receipt, current | change)


def test_explicit_cli_supersession_never_sends_claims_or_authorizes(world, monkeypatch, capsys):
    root, dispatcher, binding, tracker, panes = world
    old = interrupted(world, monkeypatch)
    tracker.update('work-1', status='open', assignee='')
    monkeypatch.setattr(cli, '_tracker', lambda _: tracker)
    monkeypatch.setattr(cli, '_registry', lambda _: dispatcher.registry)
    monkeypatch.setattr(cli, '_panes', lambda _: panes)
    monkeypatch.setattr(cli, '_wire', lambda _: pytest.fail('dispatch must not run'))
    before_item = tracker.get('work-1')
    argv = ['--root', str(root), 'go', 'work-1', 'worker', '--supersede', '--receipt', old['id']]
    assert cli.main(argv) == 0
    import json
    result = json.loads(capsys.readouterr().out)
    assert result['state'] == 'superseded' and not result['execution_authorized']
    before = snapshot(root)
    assert cli.main(argv) == 0
    assert snapshot(root) == before
    assert tracker.get('work-1') == before_item and len(panes.sent) == 1
    assert cli.main(argv + ['--reconcile']) != 0
