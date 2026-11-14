"""Superseded native CAS attempts retain evidence without blocking fresh work."""
import pytest

from shantytown import cli
from shantytown.dispatch import DispatchedButUntracked, SendUnverified
from shantytown.dispatch_receipts import (ReceiptConflict, assignment_supersession,
                                         prepared_supersession)
from shantytown.protocols import SubmissionObserved
from test_dispatch_binding import world, snapshot


def prepared(world):
    _, dispatcher, binding, _, panes = world
    panes._drops = True
    with pytest.raises(SendUnverified):
        dispatcher.go('work-1', 'worker')
    return binding.store.pending('work-1')


def test_prepared_attempt_can_be_retired_without_claim_or_delivery_guess(world):
    root, dispatcher, binding, tracker, panes = world
    old = prepared(world)
    current = tracker.get('work-1')
    sent = list(panes.sent)
    with pytest.raises(ReceiptConflict, match='pending'):
        dispatcher.go('work-1', 'worker')
    result = binding.supersede(old['id'])
    assert result['state'] == 'superseded' and not result['execution_authorized']
    assert tracker.get('work-1') == current and panes.sent == sent
    retired = binding.store.read(old['id'])
    assert retired['supersession']['kind'] == 'prepared-no-claim'
    assert retired['supersession']['revision'] == current.revision
    for key in ('text', 'body_sha256', 'submission', 'assignment', 'revision', 'request'):
        assert retired[key] == old[key]
    assert not binding.reconcile(old['id'])['execution_authorized']
    before = snapshot(root)
    assert binding.supersede(old['id']) == result
    with pytest.raises(ReceiptConflict):
        binding.store.submitted(old['id'], SubmissionObserved(old['pane'], old['body_sha256']))
    with pytest.raises(ReceiptConflict):
        binding.store.assign(old['id'], old, lambda _: pytest.fail('old claim retried'))
    with pytest.raises(ReceiptConflict):
        binding.store.prepare(old, old['text'], ident=old['id'])
    assert snapshot(root) == before
    panes._drops = False
    new = dispatcher.go('work-1', 'worker')
    assert new.receipt_id != old['id'] and not new.replayed
    assert binding.reconcile(new.receipt_id)['execution_authorized']
    assert len(panes.sent) == len(sent) + 1


@pytest.mark.parametrize('change', ['owner', 'status', 'deferred', 'read-unknown'])
def test_prepared_retirement_refuses_unreleased_or_unknown_native_state(world, monkeypatch, change):
    root, _, binding, tracker, panes = world
    old = prepared(world)
    if change == 'owner':
        tracker.update('work-1', assignee='other')
    elif change == 'status':
        tracker.update('work-1', status='in_progress')
    elif change == 'deferred':
        tracker.update('work-1', defer_until='2099-01-01T00:00:00Z')
    else:
        monkeypatch.setattr(binding.assignments, 'supersession',
                            lambda _: (_ for _ in ()).throw(OSError('unreadable')))
    before = snapshot(root)
    with pytest.raises((ReceiptConflict, OSError)):
        binding.supersede(old['id'])
    assert binding.store.read(old['id'])['state'] == 'prepared'
    # Lock creation is already present from preparation, so no ledger write.
    assert snapshot(root) == before and len(panes.sent) == 1


@pytest.mark.parametrize('flag', ['--dry-run', '-n'])
def test_prepared_cli_retirement_preview_is_read_only(world, monkeypatch, capsys, flag):
    import json
    root, dispatcher, binding, tracker, panes = world
    old = prepared(world)
    monkeypatch.setattr(cli, '_tracker', lambda _: tracker)
    monkeypatch.setattr(cli, '_registry', lambda _: dispatcher.registry)
    monkeypatch.setattr(cli, '_panes', lambda _: panes)
    monkeypatch.setattr(cli, '_wire', lambda _: pytest.fail('preview dispatched'))
    before = snapshot(root)
    assert cli.main(['--root', str(root), 'go', 'work-1', 'worker', '--supersede',
                     '--receipt', old['id'], flag]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['would_supersede'] and not output['execution_authorized']
    assert output['state'] == 'prepared' and snapshot(root) == before


@pytest.mark.parametrize('field,value', [('submission', {}), ('assignment', {}),
                                         ('state', 'submitted'), ('state', 'assigning')])
def test_prepared_retirement_cannot_downgrade_observed_or_uncertain_attempt(world, field, value):
    _, _, binding, tracker, _ = world
    old = prepared(world)
    current = dict(id='work-1', revision=tracker.get('work-1').revision,
                   status='open', assignee=None)
    with pytest.raises(ReceiptConflict):
        prepared_supersession(old | {field: value}, current)


def test_prepared_supersession_cannot_forge_uncertain_claim_release(world, monkeypatch):
    root, _, binding, tracker, _ = world
    old = interrupted(world, monkeypatch)
    proof = dict(receipt=old['id'], item='work-1', revision=old['revision'],
                 status='open', assignee=None, kind='prepared-no-claim')
    before = snapshot(root)
    with pytest.raises(ReceiptConflict):
        binding.store.supersede_assignment(old['id'], proof)
    assert snapshot(root) == before


def test_prepared_retirement_checks_native_identity_and_revision(world):
    _, _, binding, tracker, _ = world
    old = prepared(world)
    current = dict(id='work-1', revision=tracker.get('work-1').revision,
                   status='open', assignee=None)
    for bad in [dict(id='other'), dict(revision=True), dict(revision=0)]:
        with pytest.raises(ReceiptConflict):
            prepared_supersession(old, current | bad)


def test_idle_codex_queued_input_retirement_uses_real_transport_without_resend(world, monkeypatch):
    from shantytown import tmux
    from test_codex_submission import READY, FOOTER
    root, dispatcher, binding, tracker, panes = world
    adapter = tmux.Tmux(root=root)
    calls = []
    panes.screen = READY
    monkeypatch.setattr(adapter, 'foreground', lambda _: 'codex')
    monkeypatch.setattr(adapter, 'runtime_identity', lambda _: panes.process_identity)
    monkeypatch.setattr(adapter, 'session_created', lambda _: 123)
    monkeypatch.setattr(tmux, '_journal_send', lambda *_: None)
    monkeypatch.setattr(tmux, '_CODEX_POLLS', 2)
    monkeypatch.setattr(tmux.time, 'sleep', lambda _: None)
    monkeypatch.setattr(tmux.subprocess, 'run', lambda argv, **kw: calls.append(argv))

    def send(pane, text):
        typed = '\x1b[1m›\x1b[0m ' + text + '\n' + FOOTER
        queued = '• Queued follow-up inputs\n  ↳ ' + text + '\n' + READY
        frames = iter([READY, typed, queued])
        monkeypatch.setattr(adapter, 'capture', lambda *a, **kw: next(frames, queued))
        return adapter.send(pane, text)

    monkeypatch.setattr(panes, 'send', send)
    with pytest.raises(tmux.PaneSubmissionUnverified, match='queued'):
        dispatcher.go('work-1', 'worker')
    old = binding.store.pending('work-1')
    assert old['state'] == 'prepared' and old['submission'] is None
    assert tracker.get('work-1').assignee is None
    # Long dispatches use several literal chunks, but exactly one body.
    assert ''.join(c[-1] for c in calls if 'send-keys' in c and '-l' in c) == old['text']
    with pytest.raises(ReceiptConflict, match='pending'):
        dispatcher.go('work-1', 'worker')
    before = list(calls)
    assert binding.supersede(old['id'])['state'] == 'superseded'
    assert calls == before and tracker.get('work-1').assignee is None
    assert not binding.reconcile(old['id'])['execution_authorized']


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


@pytest.mark.parametrize('flag', ['--dry-run', '-n'])
def test_cli_supersession_dry_run_preserves_receipt_fence(world, monkeypatch, capsys, flag):
    import json
    root, dispatcher, binding, tracker, panes = world
    old = interrupted(world, monkeypatch)
    tracker.update('work-1', status='open', assignee='')
    monkeypatch.setattr(cli, '_tracker', lambda _: tracker)
    monkeypatch.setattr(cli, '_registry', lambda _: dispatcher.registry)
    monkeypatch.setattr(cli, '_panes', lambda _: panes)
    monkeypatch.setattr(cli, '_wire', lambda _: pytest.fail('dry-run dispatched'))
    before = snapshot(root)
    sent = list(panes.sent)
    argv = ['--root', str(root), 'go', 'work-1', 'worker',
            '--supersede', '--receipt', old['id'], flag]
    assert cli.main(argv) == 0
    output = json.loads(capsys.readouterr().out)
    assert binding.store.read(old['id'])['state'] == 'assigning'
    assert snapshot(root) == before and panes.sent == sent
    assert output['dry_run'] and not output['execution_authorized']
    assert output['state'] == 'assigning' and output['would_supersede']


@pytest.mark.parametrize('flag', ['--dry-run', '-n'])
def test_cli_supersession_dry_run_refuses_unproven_release(world, monkeypatch, capsys, flag):
    root, dispatcher, binding, tracker, panes = world
    old = interrupted(world, monkeypatch)
    monkeypatch.setattr(cli, '_tracker', lambda _: tracker)
    monkeypatch.setattr(cli, '_registry', lambda _: dispatcher.registry)
    monkeypatch.setattr(cli, '_panes', lambda _: panes)
    monkeypatch.setattr(cli, '_wire', lambda _: pytest.fail('dry-run dispatched'))
    before = snapshot(root)
    sent = list(panes.sent)
    assert cli.main(['--root', str(root), 'go', 'work-1', 'worker',
                     '--supersede', '--receipt', old['id'], flag]) != 0
    assert snapshot(root) == before and panes.sent == sent
    assert binding.store.read(old['id'])['state'] == 'assigning'
