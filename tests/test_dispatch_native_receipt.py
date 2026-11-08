"""Exercise the actual Seeds command adapter without a live board or send."""
import copy
import json
from types import SimpleNamespace

import pytest

from shantytown.dispatch_receipts import (ReceiptConflict, ReceiptStore,
                                         assignment_comment)
from shantytown.protocols import SubmissionObserved
from shantytown.sd import SdTracker


def fixture(tmp_path):
    store = ReceiptStore(tmp_path)
    scope = dict(item='work-1', revision=4, worker='worker', pane='%5',
                 session=123, task_sha256='task', scope_sha256='scope')
    receipt, _ = store.prepare(scope, 'the exact work')
    store.submitted(receipt['id'], SubmissionObserved('%5', receipt['body_sha256']))
    current = dict(id='work-1', revision=5, assignee='worker',
                   status='in_progress', comments=[dict(text=assignment_comment(receipt))])
    tracker = SdTracker.__new__(SdTracker)
    calls = []
    def command(item, *args):
        calls.append((item, args))
        return SimpleNamespace(returncode=0, stderr='', stdout=json.dumps([current]))
    tracker._bd_for = command
    return store, scope, receipt, current, tracker, calls


def test_exact_native_cas_and_receipt_readback_replay_once(tmp_path):
    store, scope, receipt, current, tracker, calls = fixture(tmp_path)
    updates = dict(status='in_progress', assignee='worker')
    claim = lambda row: tracker.dispatch_assignment(row, updates)
    assigned = store.assign(receipt['id'], scope, claim)
    assert assigned['state'] == 'assigned'
    assert calls[0][0] == 'work-1'
    assert '--if-revision=4' in calls[0][1]
    assert '--transition-comment=' + assignment_comment(receipt) in calls[0][1]
    assert '--json' in calls[0][1]
    assert calls[1] == ('work-1', ('show', 'work-1', '--json'))
    assert store.assign(receipt['id'], scope, claim) == assigned
    assert len(calls) == 2


@pytest.mark.parametrize('change', [dict(comments=[]), dict(assignee='other'),
    dict(status='open'), dict(revision=4), dict(revision=6), dict(id='other'),
    dict(defer_until='2099-01-01T00:00:00Z')])
def test_exit_zero_and_matching_owner_do_not_replace_native_receipt(tmp_path, change):
    store, scope, receipt, current, tracker, calls = fixture(tmp_path)
    current.update(change)
    with pytest.raises((ReceiptConflict, ValueError)):
        store.assign(receipt['id'], scope,
                     lambda row: tracker.dispatch_assignment(row, dict(status='in_progress', assignee='worker')))
    assert store.read(receipt['id'])['state'] == 'assigning'
    before = copy.deepcopy(calls)
    with pytest.raises(ReceiptConflict, match='reconcile'):
        store.assign(receipt['id'], scope, lambda row: pytest.fail('second write'))
    assert calls == before


def test_late_native_readback_repairs_without_second_write(tmp_path):
    store, scope, receipt, current, tracker, calls = fixture(tmp_path)
    def interrupted(row):
        tracker.dispatch_assignment(row, dict(status='in_progress', assignee='worker'))
        raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        store.assign(receipt['id'], scope, interrupted)
    proof = tracker.dispatch_assignment_read(receipt)
    assert all(args[0] == 'show' for _, args in calls[2:])
    assert store.recover_assignment(receipt['id'], proof)['state'] == 'assigned'


@pytest.mark.parametrize('code,returncode', [('CONFLICT', 4), ('INDETERMINATE', 8)])
def test_native_uncertainty_keeps_operation_diagnostics_and_is_never_retried(tmp_path, code, returncode):
    from shantytown.br import UpdateConflict, UpdateIndeterminate
    store, scope, receipt, current, tracker, calls = fixture(tmp_path)
    payload = dict(code=code, message='fixture', details=dict(operation_id='operation-1'))
    def command(item, *args):
        calls.append((item, args))
        return SimpleNamespace(returncode=returncode, stderr='', stdout=json.dumps(dict(error=payload)))
    tracker._bd_for = command
    expected = UpdateConflict if returncode == 4 else UpdateIndeterminate
    with pytest.raises(expected) as caught:
        store.assign(receipt['id'], scope,
                     lambda row: tracker.dispatch_assignment(row, dict(status='in_progress', assignee='worker')))
    assert caught.value.error == payload
    assert len(calls) == 1
    assert store.read(receipt['id'])['state'] == 'assigning'
    assert store.read(receipt['id'])['assignment_error']['native'] == payload
