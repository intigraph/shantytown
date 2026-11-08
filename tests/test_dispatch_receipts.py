"""Receipt recovery must never become another send or an unguarded claim."""

import pytest

from shantytown.dispatch_receipts import ReceiptStore, ReceiptConflict
from shantytown.protocols import SubmissionObserved


def scope(**extra):
    return dict(item='item-1', revision=4, worker='worker', pane='%5',
                session=123, task_sha256='task', scope_sha256='scope') | extra


def prepared(tmp_path):
    store = ReceiptStore(tmp_path)
    with store.lock('item-1'):
        row, fresh = store.prepare(scope(), 'do exactly this')
    assert fresh
    return store, row


def test_intent_survives_interruption_and_replay_is_same_receipt(tmp_path):
    store, row = prepared(tmp_path)
    again = ReceiptStore(tmp_path)
    with again.lock('item-1'):
        replay, fresh = again.prepare(scope(), 'do exactly this')
    assert not fresh and replay == row
    assert again.status(row['id'], scope())['missing'] == ['submission', 'assignment']
    assert len(list(store.root.glob('*.json'))) == 1


@pytest.mark.parametrize('changed', [dict(worker='other'), dict(revision=5),
    dict(session=124), dict(scope_sha256='other'), dict(task_sha256='other')])
def test_pending_receipt_cannot_authorize_another_scope(tmp_path, changed):
    store, row = prepared(tmp_path)
    with store.lock('item-1'), pytest.raises(ReceiptConflict):
        store.prepare(scope(**changed), 'do exactly this')
    assert store.status(row['id'], scope(**changed))['state'] == 'stale'


def test_old_item_echo_is_not_submission_evidence(tmp_path):
    store, row = prepared(tmp_path)
    with pytest.raises(ReceiptConflict):
        store.submitted(row['id'], SubmissionObserved('%5', 'old-body'))
    assert store.read(row['id'])['submission'] is None


def test_submission_is_bound_to_body_and_pane(tmp_path):
    store, row = prepared(tmp_path)
    store.submitted(row['id'], SubmissionObserved('%5', row['body_sha256']))
    assert store.status(row['id'], scope())['missing'] == ['assignment']
    with pytest.raises(ReceiptConflict):
        store.submitted(row['id'], SubmissionObserved('%6', row['body_sha256']))


def test_claim_requires_submission_and_current_exact_revision(tmp_path):
    store, row = prepared(tmp_path)
    calls = []
    claim = lambda r: calls.append(r) or {'receipt': r['id'], 'revision': 5}
    with pytest.raises(ReceiptConflict):
        store.assign(row['id'], scope(), claim)
    store.submitted(row['id'], SubmissionObserved('%5', row['body_sha256']))
    with pytest.raises(ReceiptConflict):
        store.assign(row['id'], scope(revision=5), claim)
    assert not calls
    assigned = store.assign(row['id'], scope(), claim)
    assert assigned['state'] == 'assigned' and len(calls) == 1
    assert store.assign(row['id'], scope(), claim) == assigned and len(calls) == 1


def test_interrupted_claim_is_not_retried_without_native_receipt_proof(tmp_path):
    store, row = prepared(tmp_path)
    store.submitted(row['id'], SubmissionObserved('%5', row['body_sha256']))
    calls = []
    def interrupted(r):
        calls.append(r)
        raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        store.assign(row['id'], scope(), interrupted)
    with pytest.raises(ReceiptConflict, match='reconcile'):
        store.assign(row['id'], scope(), interrupted)
    assert len(calls) == 1
    proof = {'receipt': row['id'], 'revision': 5}
    assert store.recover_assignment(row['id'], proof)['state'] == 'assigned'
    assert store.assign(row['id'], scope(), interrupted)['state'] == 'assigned'
    assert len(calls) == 1


def test_status_is_read_only_even_when_evidence_is_stale(tmp_path):
    store, row = prepared(tmp_path)
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in store.root.iterdir()}
    result = store.status(row['id'], scope(session=999))
    assert result['state'] == 'stale' and not result['execution_authorized']
    assert before == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in store.root.iterdir()}


def test_failed_claim_remains_recoverable_and_never_claims_success(tmp_path):
    store, row = prepared(tmp_path)
    store.submitted(row['id'], SubmissionObserved('%5', row['body_sha256']))
    with pytest.raises(ReceiptConflict, match='proof'):
        store.assign(row['id'], scope(), lambda r: {'revision': 5})
    assert store.read(row['id'])['state'] == 'assigning'
    assert not store.status(row['id'], scope())['execution_authorized']
    with pytest.raises(ReceiptConflict):
        store.recover_assignment(row['id'], {'receipt': 'other', 'revision': 5})


def test_assigned_status_requires_native_post_assignment_revision(tmp_path):
    store, row = prepared(tmp_path)
    store.submitted(row['id'], SubmissionObserved('%5', row['body_sha256']))
    store.assign(row['id'], scope(), lambda r: {'receipt': r['id'], 'revision': 5})
    assert not store.status(row['id'], scope())['execution_authorized']
    assert store.status(row['id'], scope(revision=5))['execution_authorized']
    assert not store.status(row['id'], scope(revision=6))['execution_authorized']
    replay, fresh = store.prepare(scope(revision=5), 'do exactly this')
    assert not fresh and replay['id'] == row['id']


def test_cross_instance_claim_cannot_double_enter_native_transaction(tmp_path):
    import threading
    store, row = prepared(tmp_path)
    store.submitted(row['id'], SubmissionObserved('%5', row['body_sha256']))
    entered, release = threading.Event(), threading.Event()
    outcomes = []
    def claim(r):
        entered.set()
        assert release.wait(3)
        return {'receipt': r['id'], 'revision': 5}
    def first():
        outcomes.append(store.assign(row['id'], scope(), claim))
    thread = threading.Thread(target=first)
    thread.start()
    try:
        assert entered.wait(3)
        with pytest.raises(ReceiptConflict):
            ReceiptStore(tmp_path).assign(row['id'], scope(), lambda r: pytest.fail('duplicate claim'))
    finally:
        release.set()
        thread.join(3)
    assert len(outcomes) == 1 and outcomes[0]['state'] == 'assigned'
