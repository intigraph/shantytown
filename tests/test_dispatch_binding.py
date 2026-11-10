"""Real go/ledger/file CAS composition, with only the terminal substituted."""
from dataclasses import replace
import hashlib
import json

import pytest

from shantytown import cli
from shantytown.dispatch import Dispatcher, DispatchedButUntracked, SendUnverified, TriageRefused
from shantytown.dispatch_binding import binding_for
from shantytown.dispatch_receipts import ReceiptConflict
from shantytown.feed_audit import FeedAudit
from shantytown.files import FilesRegistry, FilesTracker
from shantytown.protocols import SubmissionObserved
from shantytown.tmux import NullPanes


class ReceivingPanes(NullPanes):
    def __init__(self, **kw):
        kw.setdefault('created', {'%5': 123})
        super().__init__(**kw)
        self.process_identity = 'fixture-process-1'

    def runtime_identity(self, pane):
        return self.process_identity

    def send(self, pane, text, **kw):
        super().send(pane, text, **kw)
        if not self._drops:
            return SubmissionObserved(pane, hashlib.sha256(text.encode()).hexdigest())


@pytest.fixture
def world(tmp_path):
    (tmp_path / 'crew').mkdir()
    (tmp_path / 'crew/worker.json').write_text(json.dumps(dict(pane='%5', harness='codex')))
    registry = FilesRegistry(tmp_path / 'crew')
    tracker = FilesTracker(tmp_path / 'items')
    tracker.update('work-1', title='bounded work', status='open', priority=2)
    panes = ReceivingPanes(screen='')
    binding = binding_for(tmp_path, tracker, registry, panes)
    dispatcher = Dispatcher(registry, tracker, panes, binding=binding, audit=FeedAudit(tmp_path))
    return tmp_path, dispatcher, binding, tracker, panes


def snapshot(root):
    return {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in root.rglob('*') if p.is_file()}


def test_real_go_exact_body_single_assignment_and_replay(world):
    root, d, binding, tracker, panes = world
    p = d.go('work-1', 'worker', note='scope qualifier', quipu_nodes=['context'])
    assert p.receipt_id and not p.replayed
    assert p.serve_id == p.receipt_id and 'proceed only when execution_authorized is true' in p.text
    current = tracker.get('work-1')
    assert current.revision == 2 and current.assignee == 'worker'
    before = snapshot(root)
    status = binding.reconcile(p.receipt_id)
    assert status['execution_authorized'] and status['missing'] == []
    assert status['native_assignment']['receipt'] == p.receipt_id
    assert snapshot(root) == before
    again = d.go('work-1', 'worker', note='scope qualifier', quipu_nodes=['context'])
    assert again.replayed and again.receipt_id == p.receipt_id and again.text == p.text
    assert tracker.get('work-1') == current and len(panes.sent) == 1


def test_sent_without_positive_observation_stays_pending_and_never_resends(world):
    root, d, binding, tracker, panes = world
    panes._drops = True
    with pytest.raises(SendUnverified):
        d.go('work-1', 'worker')
    row = binding.store.pending('work-1')
    assert row['state'] == 'prepared'
    assert tracker.get('work-1').status == 'open'
    with pytest.raises(ReceiptConflict, match='pending'):
        d.go('work-1', 'worker')
    assert len(panes.sent) == 1
    before = snapshot(root)
    assert binding.reconcile(row['id'])['missing'] == ['submission', 'assignment']
    assert before == snapshot(root)


def test_completion_finishes_exact_original_receipt_without_second_send(world, monkeypatch):
    root, d, binding, tracker, panes = world
    panes._drops = True
    with pytest.raises(SendUnverified):
        d.go('work-1', 'worker', note='original qualifier', quipu_nodes=['original-context'])
    row = binding.store.pending('work-1')
    observed = SubmissionObserved(row['pane'], row['body_sha256'], {'kind':'fixture-native-consumed'})
    monkeypatch.setattr(panes, 'observed_submission', lambda *a: observed, raising=False)
    before = snapshot(root)
    assert not d.complete('work-1', 'worker', dry_run=True, receipt=row['id'])['execution_authorized']
    assert snapshot(root) == before
    result = d.complete('work-1', 'worker', receipt=row['id'])
    assert result['execution_authorized']
    assert len(panes.sent) == 1 and tracker.get('work-1').revision == 2
    assert binding.store.read(row['id'])['text'] == row['text']
    assert binding.store.read(row['id'])['submission']['source'] == observed.source
    again = snapshot(root)
    assert d.complete('work-1', 'worker', receipt=row['id'])['execution_authorized']
    assert snapshot(root) == again and len(panes.sent) == 1


def test_completion_without_positive_proof_or_after_runtime_change_is_fenced(world, monkeypatch):
    root, d, binding, tracker, panes = world
    panes._drops = True
    with pytest.raises(SendUnverified):
        d.go('work-1', 'worker')
    row = binding.store.pending('work-1')
    with pytest.raises(ReceiptConflict, match='submission unconfirmed'):
        d.complete('work-1', 'worker', receipt=row['id'])
    panes.process_identity = 'replacement-process'
    monkeypatch.setattr(panes, 'observed_submission', lambda *a:
        SubmissionObserved(row['pane'], row['body_sha256']), raising=False)
    with pytest.raises(ReceiptConflict, match='stale'):
        d.complete('work-1', 'worker', receipt=row['id'])
    assert tracker.get('work-1').revision == 1 and len(panes.sent) == 1


def test_completion_recovers_interrupted_native_claim_without_repeating_it(world, monkeypatch):
    root, d, binding, tracker, panes = world
    original = binding.assignments.claim
    calls = []
    def interrupted(row, updates):
        calls.append(row['id'])
        original(row, updates)
        raise KeyboardInterrupt()
    monkeypatch.setattr(binding.assignments, 'claim', interrupted)
    with pytest.raises(KeyboardInterrupt):
        d.go('work-1', 'worker')
    row = binding.store.pending('work-1')
    assert row['state'] == 'assigning'
    assert d.complete('work-1', 'worker', receipt=row['id'])['execution_authorized']
    assert len(calls) == len(panes.sent) == 1


def test_completion_keeps_governor_and_native_uncertainty_fences(world, monkeypatch):
    from shantytown.dispatch import GovernorRefused
    root, d, binding, tracker, panes = world
    panes._drops = True
    with pytest.raises(SendUnverified):
        d.go('work-1', 'worker')
    row = binding.store.pending('work-1')
    monkeypatch.setattr(panes, 'observed_submission', lambda *a:
        SubmissionObserved(row['pane'], row['body_sha256']), raising=False)
    d.governor = lambda *a: 'fixture governor hold'
    with pytest.raises(GovernorRefused):
        d.complete('work-1', 'worker', receipt=row['id'])
    assert binding.store.read(row['id'])['state'] == 'prepared'
    d.governor = None
    calls = []
    def uncertain(*a):
        calls.append(True)
        raise ReceiptConflict('fixture native outcome UNKNOWN')
    monkeypatch.setattr(binding.assignments, 'claim', uncertain)
    with pytest.raises(ReceiptConflict):
        d.complete('work-1', 'worker', receipt=row['id'])
    with pytest.raises(ReceiptConflict):
        d.complete('work-1', 'worker', receipt=row['id'])
    assert len(calls) == len(panes.sent) == 1
    assert binding.store.read(row['id'])['state'] == 'assigning'


def test_interrupt_before_send_retains_intent_and_no_claim(world, monkeypatch):
    root, d, binding, tracker, panes = world
    monkeypatch.setattr(panes, 'send', lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        d.go('work-1', 'worker')
    assert binding.store.pending('work-1')['state'] == 'prepared'
    assert tracker.get('work-1').status == 'open'


def test_interrupt_after_native_commit_recovers_from_actual_proof_without_second_claim(world, monkeypatch):
    root, d, binding, tracker, panes = world
    claim = binding.assignments.claim
    calls = []
    def interrupted(row, updates):
        calls.append(row['id'])
        claim(row, updates)
        raise KeyboardInterrupt()
    monkeypatch.setattr(binding.assignments, 'claim', interrupted)
    with pytest.raises(KeyboardInterrupt):
        d.go('work-1', 'worker')
    row = binding.store.pending('work-1')
    before = snapshot(root)
    result = binding.reconcile(row['id'])
    assert result['native_assignment']['receipt'] == row['id']
    assert snapshot(root) == before and result['missing'] == ['local_assignment']
    assert result['execution_authorized'] and result['state'] == 'native_assigned'
    p = d.go('work-1', 'worker')
    assert p.receipt_id == row['id'] and p.replayed
    assert len(calls) == 1 and len(panes.sent) == 1
    assert binding.reconcile(row['id'])['execution_authorized']


@pytest.mark.parametrize('change', ['task', 'session', 'process', 'card', 'note', 'worker'])
def test_changed_scope_cannot_replay_pending(world, change):
    root, d, binding, tracker, panes = world
    panes._drops = True
    with pytest.raises(SendUnverified):
        d.go('work-1', 'worker')
    kw = {}
    worker = 'worker'
    if change == 'task':
        tracker.update('work-1', title='changed task')
    elif change == 'session':
        panes._created['%5'] = 124
    elif change == 'process':
        panes.process_identity = 'fixture-process-2'
    elif change == 'card':
        path = root / 'crew/worker.json'
        path.write_text(json.dumps(dict(pane='%5', harness='claude')))
    elif change == 'note':
        kw['note'] = 'different qualifier'
    else:
        (root / 'crew/other.json').write_text(json.dumps(dict(pane='%5', harness='codex')))
        worker = 'other'
    with pytest.raises(ReceiptConflict):
        d.go('work-1', worker, **kw)
    assert len(panes.sent) == 1 and tracker.get('work-1').status == 'open'


def test_busy_refuses_without_receipt_send_or_assignment(world):
    root, d, binding, tracker, panes = world
    panes.screen = 'esc to interrupt'
    with pytest.raises(TriageRefused):
        d.go('work-1', 'worker')
    assert not binding.store.root.exists() and not panes.sent
    assert tracker.get('work-1').status == 'open'


def test_task_edit_during_send_refuses_native_claim(world, monkeypatch):
    root, d, binding, tracker, panes = world
    send = panes.send
    def concurrent(pane, text):
        proof = send(pane, text)
        tracker.update('work-1', title='changed during send')
        return proof
    monkeypatch.setattr(panes, 'send', concurrent)
    with pytest.raises(DispatchedButUntracked):
        d.go('work-1', 'worker')
    assert tracker.get('work-1').assignee is None
    assert binding.store.pending('work-1')['state'] == 'submitted'


def test_reconcile_cli_is_read_only_even_for_interrupted_assignment(world, monkeypatch, capsys):
    root, d, binding, tracker, panes = world
    p = d.go('work-1', 'worker')
    monkeypatch.setattr(cli, '_tracker', lambda _: tracker)
    monkeypatch.setattr(cli, '_registry', lambda _: d.registry)
    monkeypatch.setattr(cli, '_panes', lambda _: panes)
    monkeypatch.setattr(cli, '_wire', lambda _: pytest.fail('dispatch wiring must not run'))
    before = snapshot(root)
    assert cli.main(['--root', str(root), 'go', 'work-1', 'worker', '--reconcile', '--receipt', p.receipt_id]) == 0
    assert json.loads(capsys.readouterr().out)['execution_authorized']
    assert before == snapshot(root) and len(panes.sent) == 1


def test_completion_cli_is_explicit_policy_checked_and_never_sends(world, monkeypatch, capsys):
    root, d, binding, tracker, panes = world
    panes._drops = True
    with pytest.raises(SendUnverified):
        d.go('work-1', 'worker')
    row = binding.store.pending('work-1')
    monkeypatch.setattr(cli, '_tracker', lambda _: tracker)
    monkeypatch.setattr(cli, '_registry', lambda _: d.registry)
    monkeypatch.setattr(cli, '_panes', lambda _: panes)
    wired = []
    monkeypatch.setattr(cli, '_wire', lambda _: wired.append(True) or d)
    monkeypatch.setattr(panes, 'observed_submission', lambda *a:
        SubmissionObserved(row['pane'], row['body_sha256']), raising=False)
    argv = ['--root', str(root), 'go', 'work-1', 'worker', '--complete', '--receipt', row['id']]
    monkeypatch.setattr(cli.agent_hold, 'reason', lambda *a: 'operator hold')
    assert cli.main(argv) == cli.REFUSED and not wired
    capsys.readouterr()
    monkeypatch.setattr(cli.agent_hold, 'reason', lambda *a: '')
    assert cli.main(argv + ['--reconcile']) == cli.CANNOT_TELL and not wired
    capsys.readouterr()
    assert cli.main(argv) == cli.OK
    assert json.loads(capsys.readouterr().out)['execution_authorized']
    assert wired == [True] and len(panes.sent) == 1


@pytest.mark.parametrize('state', ['delivered', 'queued', 'dequeued', 'acknowledged', 'superseded'])
def test_pending_recovery_refuses_terminal_state_without_submission_witness(world, state):
    from shantytown.delivery import Custody
    root, d, binding, tracker, panes = world
    panes._drops = True
    with pytest.raises(SendUnverified):
        d.go('work-1', 'worker')
    row = binding.store.pending('work-1')
    with Custody(root, '%5') as custody:
        custody.begin(row['text'], 123)
        custody.finish(state)
    with pytest.raises(ReceiptConflict, match='pending'):
        d.go('work-1', 'worker')
    assert tracker.get('work-1').assignee is None
    assert len(panes.sent) == 1


def test_unknown_process_identity_refuses_before_any_intent_or_send(world):
    root, d, binding, tracker, panes = world
    panes.process_identity = None
    with pytest.raises(ReceiptConflict, match='process identity UNKNOWN'):
        d.go('work-1', 'worker')
    assert not binding.store.root.exists() and not panes.sent


def test_reconcile_changed_process_is_stale_and_read_only(world):
    root, d, binding, tracker, panes = world
    p = d.go('work-1', 'worker')
    panes.process_identity = 'replacement-process'
    before = snapshot(root)
    status = binding.reconcile(p.receipt_id)
    assert status['state'] == 'stale' and not status['execution_authorized']
    assert snapshot(root) == before


def test_cas_conflict_after_submission_never_claims_or_retries(world, monkeypatch):
    root, d, binding, tracker, panes = world
    claim = binding.assignments.claim
    def race(row, updates):
        tracker.update(row['item'], notes='another legitimate write')
        return claim(row, updates)
    monkeypatch.setattr(binding.assignments, 'claim', race)
    with pytest.raises(DispatchedButUntracked):
        d.go('work-1', 'worker')
    row = binding.store.pending('work-1')
    assert row['assignment_error']['native']['code'] == 'CONFLICT'
    assert tracker.get('work-1').assignee is None
    with pytest.raises(ReceiptConflict):
        d.go('work-1', 'worker')
    assert len(panes.sent) == 1


@pytest.mark.parametrize('observed,stable_runtime', [(False, True), (True, True), (True, False)])
def test_actual_tmux_wrapper_recovery_requires_positive_observation(world, observed, stable_runtime):
    from shantytown.tmux import Tmux
    root, d, binding, tracker, panes = world
    transport = Tmux(root=root)
    identities = iter([panes.process_identity, panes.process_identity if stable_runtime else 'changed'])
    transport.runtime_identity = lambda _: next(identities)
    calls = []

    def send(pane, text, *, custody=None):
        calls.append(text)
        custody.begin(text, 123)
        return SubmissionObserved(pane, hashlib.sha256(text.encode()).hexdigest()) if observed else None

    transport._send = send
    # Simulate coordinator interruption after the real transport returns,
    # before its observation reaches the dispatch ledger.
    def interrupted(pane, text):
        transport.send(pane, text)
        return None
    panes.send = interrupted
    with pytest.raises(SendUnverified):
        d.go('work-1', 'worker')
    row = binding.store.pending('work-1')
    assert tracker.get('work-1').assignee is None
    if observed and stable_runtime:
        replay = d.go('work-1', 'worker')
        assert replay.replayed and replay.receipt_id == row['id']
        assert binding.reconcile(row['id'])['execution_authorized']
    else:
        with pytest.raises(ReceiptConflict, match='pending'):
            d.go('work-1', 'worker')
        assert tracker.get('work-1').assignee is None
        assert not binding.reconcile(row['id'])['execution_authorized']
    assert len(calls) == 1


@pytest.mark.parametrize('field,value', [
    ('runtime', 'another-process'), ('runtime', None),
    ('pane', '%99'), ('body_sha256', '0' * 64),
])
def test_pending_recovery_refuses_mismatched_submission_witness(world, field, value):
    from shantytown.delivery import Custody
    root, d, binding, tracker, panes = world
    panes._drops = True
    with pytest.raises(SendUnverified):
        d.go('work-1', 'worker')
    row = binding.store.pending('work-1')
    with Custody(root, '%5') as custody:
        custody.begin(row['text'], 123)
        custody.submitted(SubmissionObserved('%5', hashlib.sha256(row['text'].encode()).hexdigest()),
                          panes.process_identity)
        custody.record['submission'][field] = value
        custody.finish('delivered')
    with pytest.raises(ReceiptConflict, match='pending'):
        d.go('work-1', 'worker')
    assert tracker.get('work-1').assignee is None
    assert not binding.reconcile(row['id'])['execution_authorized']
    assert len(panes.sent) == 1
