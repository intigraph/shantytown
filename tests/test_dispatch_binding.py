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
        super().__init__(created={'%5': 123}, **kw)

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


@pytest.mark.parametrize('change', ['task', 'session', 'card', 'note', 'worker'])
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
