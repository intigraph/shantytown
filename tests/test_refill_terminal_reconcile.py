"""Terminal composer custody cannot turn unheld work into proven delivery."""
from copy import deepcopy
import hashlib
import json

import pytest

from shantytown.answer import Answer
from shantytown import refill_terminal_reconcile as terminal
from shantytown import refill_reconcile as rr
from test_refill_reconcile import packet, put, snapshot  # shared dispatch fixture


class Tracker:
    def __init__(self, **changes):
        self.row = dict(id='work-1', status='open', assignee=None, revision=7)
        self.row.update(changes)

    def show(self, item):
        assert item == 'work-1'
        return Answer.complete_read(deepcopy(self.row), how='fixture native exact show')


@pytest.fixture
def ended(packet):
    root, _, state, custody, _ = packet
    custody.update(state='orphaned', pointer='inbox-1', pointer_state='recorded')
    path = root / 'delivery' / (custody['id'] + '.json')
    put(path, custody)
    request = dict(version=1, worker='worker', item='work-1',
                   pending=deepcopy(state['pending']['worker']), custody=custody['id'],
                   custody_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    return root, request, state, custody


def rebind(root, request, custody):
    path = root / 'delivery' / (custody['id'] + '.json')
    put(path, custody)
    request['custody_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize('owner', ['stopped', 'absent', 'live'])
@pytest.mark.parametrize('status', ['open', 'deferred', 'closed'])
@pytest.mark.parametrize('custody_state', ['orphaned', 'dequeued'])
def test_unheld_native_work_releases_exact_reservation_without_claiming_delivery(
        ended, owner, status, custody_state):
    root, request, original, custody = ended
    if owner == 'stopped':
        put(root / 'stopped/worker.json', dict(at=1002, by='operator'))
    elif owner == 'absent':
        (root / 'crew/worker.json').unlink()
    custody['state'] = custody_state
    rebind(root, request, custody)
    before = snapshot(root)
    tracker = Tracker(status=status, assignee='worker' if status == 'closed' else None)
    assert terminal.reconcile(root, request, tracker=tracker)['state'] == 'qualified'
    assert snapshot(root) == before
    result = terminal.reconcile(root, request, apply=True, tracker=tracker)
    assert result['state'] == 'reconciled' and result['delivery'] == 'UNKNOWN'
    expected = deepcopy(original)
    del expected['pending']['worker']
    assert rr.read(root / 'refill/state.json') == expected
    assert rr.read(root / 'delivery' / (custody['id'] + '.json')) == custody
    audit = rr.audit_rows(root / 'refill/terminal-reconciliations.jsonl')
    assert [x['event'] for x in audit] == ['prepared', 'completed']
    assert audit[0]['original_pending'] == request['pending']
    assert audit[0]['tracker']['revision'] == 7
    assert all(snapshot(root)[p] == value for p, value in before.items()
               if p != 'refill/state.json')
    after = snapshot(root)
    assert terminal.reconcile(root, request, apply=True, tracker=tracker)['state'] == 'already-reconciled'
    assert snapshot(root) == after


def test_lane_is_part_of_exact_reservation_and_audit(ended):
    root, request, state, _ = ended
    state['pending']['worker']['lane'] = 'next'
    put(root / 'refill/state.json', state)
    before = snapshot(root)
    with pytest.raises(ValueError):
        terminal.reconcile(root, request, apply=True, tracker=Tracker())
    assert snapshot(root) == before
    request['pending']['lane'] = 'next'
    terminal.reconcile(root, request, apply=True, tracker=Tracker())
    audit = rr.audit_rows(root / 'refill/terminal-reconciliations.jsonl')
    assert audit[0]['original_pending']['lane'] == 'next'


@pytest.mark.parametrize('owner', ['worker', 'other'])
@pytest.mark.parametrize('status', ['open', 'in_progress', 'deferred', 'blocked'])
def test_live_owner_still_holding_work_refuses_without_writes(ended, owner, status):
    root, request, *_ = ended
    before = snapshot(root)
    with pytest.raises(ValueError):
        terminal.reconcile(root, request, apply=True, tracker=Tracker(assignee=owner, status=status))
    assert snapshot(root) == before


def test_stop_stamp_does_not_override_native_ownership(ended):
    root, request, *_ = ended
    put(root / 'stopped/worker.json', dict(at=1002, by='operator'))
    before = snapshot(root)
    with pytest.raises(ValueError):
        terminal.reconcile(root, request, apply=True, tracker=Tracker(assignee='worker'))
    assert snapshot(root) == before


@pytest.mark.parametrize('mutation', ['hash', 'pointer', 'state', 'footer', 'lane', 'revision', 'missing-owner'])
def test_ambiguous_evidence_refuses_read_only(ended, mutation):
    root, request, _, custody = ended
    tracker = Tracker()
    if mutation == 'hash':
        request['custody_sha256'] = '0' * 64
    elif mutation in ('pointer', 'state', 'footer'):
        if mutation == 'pointer':
            custody['pointer_state'] = 'unknown'
        elif mutation == 'state':
            custody['state'] = 'queued'
        else:
            custody['text'] = custody['text'].replace('worker:worker', 'worker:other')
        rebind(root, request, custody)
    elif mutation == 'lane':
        request['pending']['lane'] = 'unknown'
    elif mutation == 'revision':
        tracker.row['revision'] = True
    else:
        del tracker.row['assignee']
    before = snapshot(root)
    with pytest.raises(ValueError):
        terminal.reconcile(root, request, apply=True, tracker=tracker)
    assert snapshot(root) == before


def test_tracker_partial_or_failed_read_never_clears_reservation(ended):
    root, request, *_ = ended
    class Partial:
        def show(self, item):
            raise RuntimeError('native read unavailable')
    before = snapshot(root)
    with pytest.raises(RuntimeError):
        terminal.reconcile(root, request, apply=True, tracker=Partial())
    assert snapshot(root) == before


def test_claim_after_prepare_refuses_release(ended, monkeypatch):
    root, request, _, custody = ended
    tracker = Tracker()
    append = rr.append
    def claim(path, value):
        append(path, value)
        tracker.row.update(assignee='worker', status='in_progress', revision=8)
    monkeypatch.setattr(rr, 'append', claim)
    with pytest.raises(ValueError):
        terminal.reconcile(root, request, apply=True, tracker=tracker)
    assert rr.read(root / 'refill/state.json')['pending']['worker'] == request['pending']
    assert rr.read(root / 'delivery' / (custody['id'] + '.json')) == custody


@pytest.mark.parametrize('point', ['prepared', 'state'])
def test_interrupted_release_resumes_same_audit_without_rewriting_custody(ended, monkeypatch, point):
    root, request, _, custody = ended
    append, replace = rr.append, rr.replace
    def stop_append(path, value):
        append(path, value)
        if point == 'prepared' and value['event'] == 'prepared':
            raise OSError('crash')
    def stop_replace(path, value):
        replace(path, value)
        if point == 'state':
            raise OSError('crash')
    monkeypatch.setattr(rr, 'append', stop_append)
    monkeypatch.setattr(rr, 'replace', stop_replace)
    with pytest.raises(OSError):
        terminal.reconcile(root, request, apply=True, tracker=Tracker())
    monkeypatch.setattr(rr, 'append', append)
    monkeypatch.setattr(rr, 'replace', replace)
    assert terminal.reconcile(root, request, apply=True, tracker=Tracker())['state'] == 'reconciled'
    assert rr.read(root / 'delivery' / (custody['id'] + '.json')) == custody


def test_old_receipt_cannot_release_new_reservation(ended):
    root, request, *_ = ended
    terminal.reconcile(root, request, apply=True, tracker=Tracker())
    state = rr.read(root / 'refill/state.json')
    state['pending']['worker'] = dict(item='work-1', at=2000)
    put(root / 'refill/state.json', state)
    before = snapshot(root)
    with pytest.raises(ValueError):
        terminal.reconcile(root, request, apply=True, tracker=Tracker())
    assert snapshot(root) == before


def test_capped_native_answer_cannot_prove_work_unheld(ended):
    from shantytown.answer import PartialAnswer
    root, request, *_ = ended
    class Capped:
        def show(self, item):
            return Answer.capped(dict(id=item, status='open', assignee=None, revision=7),
                                 how='capped fixture', caveat='ownership read incomplete')
    before = snapshot(root)
    with pytest.raises(PartialAnswer):
        terminal.reconcile(root, request, apply=True, tracker=Capped())
    assert snapshot(root) == before


def test_symlink_custody_cannot_supply_terminal_proof(ended, tmp_path):
    root, request, _, custody = ended
    path = root / 'delivery' / (custody['id'] + '.json')
    outside = tmp_path / 'outside.json'
    outside.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(outside)
    before = snapshot(root)
    with pytest.raises(ValueError):
        terminal.reconcile(root, request, apply=True, tracker=Tracker())
    assert snapshot(root) == before


def test_native_adapter_uses_configured_backend_without_fallback(ended, monkeypatch):
    from shantytown import feed_check
    root, request, *_ = ended
    seen = []
    class Adapter(Tracker):
        def __init__(self, actual_root, registry):
            super().__init__()
            seen.append((actual_root, registry.root))
            self.tracker = object()
    monkeypatch.setattr(feed_check, 'TrackerAdapter', Adapter)
    assert terminal.reconcile(root, request)['state'] == 'qualified'
    assert seen == [(root, root / 'crew')]
    monkeypatch.setattr(feed_check, 'TrackerAdapter', lambda *args: type('Unsupported', (), {'tracker': None})())
    before = snapshot(root)
    with pytest.raises(ValueError, match='backend unsupported'):
        terminal.reconcile(root, request, apply=True)
    assert snapshot(root) == before


def test_cli_does_not_echo_private_adapter_error(ended, monkeypatch, capsys, tmp_path):
    root, request, *_ = ended
    path = tmp_path / 'terminal.json'
    put(path, request)
    def unavailable(*args):
        raise RuntimeError('private-fixture-error')
    monkeypatch.setattr(terminal, 'native_tracker', unavailable)
    before = snapshot(root)
    assert terminal.main(['--root', str(root), '--receipt', str(path)]) == 2
    assert 'private-fixture-error' not in capsys.readouterr().out
    assert snapshot(root) == before


def test_byte_only_custody_change_after_prepare_refuses_release(ended, monkeypatch):
    root, request, *_ = ended
    append = rr.append
    path = root / 'delivery' / (request['custody'] + '.json')
    def change_bytes(journal, value):
        append(journal, value)
        path.write_bytes(path.read_bytes() + b'\n')
    monkeypatch.setattr(rr, 'append', change_bytes)
    with pytest.raises(ValueError, match='bytes changed'):
        terminal.reconcile(root, request, apply=True, tracker=Tracker())
    assert rr.read(root / 'refill/state.json')['pending']['worker'] == request['pending']
