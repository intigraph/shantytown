"""A delivered message releases one reservation; uncertainty never becomes a resend."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from shantytown import refill_reconcile as rr
from shantytown.refill import metrics


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


@pytest.fixture
def packet(tmp_path):
    root = tmp_path / 'deployment'
    for name in ('crew', 'refill', 'delivery', 'history/worker'):
        (root / name).mkdir(parents=True, exist_ok=True)
    workspace = str(tmp_path / 'workspace')
    put(root / 'crew/worker.json', dict(pane='worker-pane', workspace=workspace, harness='codex'))
    state = dict(pending={'worker': dict(item='work-1', at=1000),
                          'other': dict(item='work-2', at=999)},
                 observed_at=990, coverage=True, observations={}, waiting={'other': {'since': 950}})
    put(root / 'refill/state.json', state)
    (root / 'refill/lock').touch()
    body = 'Work is on your hook: work-1 — original task — [st serve:' + 'a' * 32 + ' worker:worker]'
    ident = 'send-' + 'b' * 32
    custody = dict(id=ident, pane='worker-pane', socket='fixture', text=body,
                   created=1001, session=900, state='unknown', recovery_attempted=False)
    put(root / 'delivery' / (ident + '.json'), custody)
    event = dict(type='response_item', timestamp='1970-01-01T00:16:50Z',
                 payload=dict(type='message', role='user', content=[dict(type='input_text', text=body)]))
    history = root / 'history/worker/rollout-session-id.jsonl'
    meta = dict(type='session_meta', timestamp='1970-01-01T00:15:00Z',
                payload=dict(id='session-id', cwd=workspace))
    raw = json.dumps(event) + '\n'
    history.write_text(json.dumps(meta) + '\n' + raw)
    request = dict(version=1, worker='worker', item='work-1', pending_at=1000,
                   custody=ident, history=history.name, line=2,
                   event_sha256=hashlib.sha256(raw.encode()).hexdigest())
    return root, request, state, custody, history


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_default_qualification_is_read_only(packet):
    root, request, *_ = packet
    before = snapshot(root)
    assert rr.reconcile(root, request, now=1100)['state'] == 'qualified'
    assert snapshot(root) == before


def test_apply_is_exact_audited_and_does_not_manufacture_natural_health(packet):
    root, request, original, custody, _ = packet
    journal = root / 'refill/observations.jsonl'
    journal.write_text('{"original":"unknown"}\n')
    assert rr.reconcile(root, request, apply=True, now=1100)['state'] == 'reconciled'
    state = rr.read(root / 'refill/state.json')
    expected = deepcopy(original)
    del expected['pending']['worker']
    assert state == expected  # All observation/error/timestamp and other reservations survive.
    record = rr.read(root / 'delivery' / (request['custody'] + '.json'))
    assert record['state'] == 'delivered' and record['text'] == custody['text']
    audit = rr.audit_rows(root / 'refill/reconciliations.jsonl')
    assert [row['event'] for row in audit] == ['prepared', 'completed']
    assert audit[0]['original_custody'] == custody
    assert audit[0]['original_pending'] == original['pending']['worker']
    assert journal.read_text() == '{"original":"unknown"}\n'
    assert 'st_refill_observation_known 0' in metrics(root, 1100)  # Other pending still unknown.
    before = snapshot(root)
    assert rr.reconcile(root, request, apply=True, now=1100)['state'] == 'already-reconciled'
    assert snapshot(root) == before


def test_release_last_pending_still_preserves_stale_and_failed_observations(packet):
    root, request, state, *_ = packet
    del state['pending']['other']
    state['observation_error'] = 'PartialAnswer'
    put(root / 'refill/state.json', state)
    rr.reconcile(root, request, apply=True, now=2000)
    assert 'st_refill_pending_dispatches 0' in metrics(root, 2000)
    assert 'st_refill_observation_known 0' in metrics(root, 2000)
    # Only a later ordinary observation can change these producer fields.
    result = rr.read(root / 'refill/state.json')
    assert result['observed_at'] == 990 and result['observation_error'] == 'PartialAnswer'


@pytest.mark.parametrize('field,value', [
    ('worker', '../worker'), ('worker', 'other'), ('item', 'work-2'),
    ('pending_at', 999), ('pending_at', True), ('line', True), ('line', 3),
    ('history', '../escape.jsonl'), ('custody', '../escape'), ('version', 2),
    ('event_sha256', '0' * 64),
])
def test_wrong_or_ambiguous_binding_does_not_write(packet, field, value):
    root, request, *_ = packet
    request[field] = value
    before = snapshot(root)
    with pytest.raises((ValueError, OSError, LookupError)):
        rr.reconcile(root, request, apply=True, now=1100)
    assert snapshot(root) == before


@pytest.mark.parametrize('mutation', ['assistant', 'compacted', 'quoted', 'different-body',
                                     'future', 'before-send', 'wrong-session', 'wrong-workspace'])
def test_native_evidence_must_be_accepted_exact_user_input(packet, mutation):
    root, request, _, _, history = packet
    meta, event = [json.loads(line) for line in history.read_text().splitlines()]
    if mutation == 'assistant':
        event['payload']['role'] = 'assistant'
    elif mutation == 'compacted':
        event['type'] = 'compacted'
    elif mutation in ('quoted', 'different-body'):
        event['payload']['content'][0]['text'] += '\nquoted' if mutation == 'quoted' else ' changed'
    elif mutation == 'future':
        event['timestamp'] = '2099-01-01T00:00:00Z'
    elif mutation == 'before-send':
        event['timestamp'] = '1970-01-01T00:16:40Z'
    elif mutation == 'wrong-session':
        meta['payload']['id'] = 'another-session'
    else:
        meta['payload']['cwd'] += '-other'
    raw = json.dumps(event) + '\n'
    history.write_text(json.dumps(meta) + '\n' + raw)
    request['event_sha256'] = hashlib.sha256(raw.encode()).hexdigest()
    before = snapshot(root)
    with pytest.raises(ValueError):
        rr.reconcile(root, request, apply=True, now=1100)
    assert snapshot(root) == before


@pytest.mark.parametrize('relative', ['refill/state.json', 'crew/worker.json',
                                     'history/worker/rollout-session-id.jsonl'])
def test_symlink_evidence_or_state_refuses(packet, tmp_path, relative):
    root, request, *_ = packet
    path = root / relative
    target = tmp_path / 'outside'
    target.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(target)
    with pytest.raises(ValueError):
        rr.reconcile(root, request, apply=True, now=1100)


def test_lock_contention_never_waits_or_sends(packet):
    import fcntl
    root, request, *_ = packet
    with (root / 'refill/lock').open('r') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            rr.reconcile(root, request, apply=True, now=1100)
    assert rr.read(root / 'refill/state.json')['pending']['worker']


@pytest.mark.parametrize('crash_after', ['prepared', 'custody', 'state'])
def test_crash_recovery_uses_same_proof_and_never_replays_dispatch(packet, monkeypatch, crash_after):
    root, request, _, _, _ = packet
    real_replace, real_append = rr.replace, rr.append
    def replacement(path, value):
        real_replace(path, value)
        if ((crash_after == 'custody' and path.parent.name == 'delivery') or
                (crash_after == 'state' and path.name == 'state.json')):
            raise OSError('simulated crash after replace')
    def append(path, value):
        real_append(path, value)
        if crash_after == 'prepared' and value['event'] == 'prepared':
            raise OSError('simulated crash after durable intent')
    monkeypatch.setattr(rr, 'replace', replacement)
    monkeypatch.setattr(rr, 'append', append)
    with pytest.raises(OSError):
        rr.reconcile(root, request, apply=True, now=1100)
    monkeypatch.setattr(rr, 'replace', real_replace)
    monkeypatch.setattr(rr, 'append', real_append)
    assert rr.reconcile(root, request, apply=True, now=1100)['state'] == 'reconciled'
    assert 'worker' not in rr.read(root / 'refill/state.json')['pending']
    assert [x['event'] for x in rr.audit_rows(root / 'refill/reconciliations.jsonl')] == ['prepared', 'completed']


def test_new_reservation_for_same_worker_is_not_removed_by_old_receipt(packet):
    root, request, *_ = packet
    rr.reconcile(root, request, apply=True, now=1100)
    state = rr.read(root / 'refill/state.json')
    state['pending']['worker'] = dict(item='work-1', at=1099)
    put(root / 'refill/state.json', state)
    before = snapshot(root)
    with pytest.raises(ValueError):
        rr.reconcile(root, request, apply=True, now=1100)
    assert snapshot(root) == before


def test_audit_failure_leaves_original_reservation_and_custody(packet, monkeypatch):
    root, request, *_ = packet
    before = snapshot(root)
    monkeypatch.setattr(rr, 'append', lambda *a: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError):
        rr.reconcile(root, request, apply=True, now=1100)
    # Composer lock creation is harmless; neither original data file was changed.
    after = snapshot(root)
    assert all(after[k] == v for k, v in before.items())


def test_partial_or_duplicate_audit_refuses_instead_of_resetting(packet):
    root, request, *_ = packet
    journal = root / 'refill/reconciliations.jsonl'
    journal.write_text('{"event":')
    with pytest.raises(ValueError):
        rr.reconcile(root, request, apply=True, now=1100)
    assert rr.read(root / 'refill/state.json')['pending']['worker']


def test_normal_shared_group_modes_do_not_require_a_permission_change(packet):
    root, request, *_ = packet
    root.chmod(0o775)
    (root / 'crew').chmod(0o775)
    (root / 'crew/worker.json').chmod(0o664)
    (root / 'refill/state.json').chmod(0o664)
    assert rr.reconcile(root, request, apply=True, now=1100)['state'] == 'reconciled'
    assert (root / 'refill/state.json').stat().st_mode & 0o777 == 0o664
    assert (root / 'refill/reconciliations.jsonl').stat().st_mode & 0o777 == 0o600


def test_world_writable_state_refuses(packet):
    root, request, *_ = packet
    (root / 'refill/state.json').chmod(0o666)
    with pytest.raises(ValueError):
        rr.reconcile(root, request, apply=True, now=1100)


def test_noncooperating_state_change_after_prepare_keeps_delivery_unknown(packet, monkeypatch):
    root, request, *_ = packet
    real_append = rr.append
    def append(path, value):
        real_append(path, value)
        state = rr.read(root / 'refill/state.json')
        state['pending']['worker'] = dict(item='new-work', at=1050)
        put(root / 'refill/state.json', state)
    monkeypatch.setattr(rr, 'append', append)
    with pytest.raises(ValueError):
        rr.reconcile(root, request, apply=True, now=1100)
    assert rr.read(root / 'delivery' / (request['custody'] + '.json'))['state'] == 'unknown'
    assert rr.read(root / 'refill/state.json')['pending']['worker']['item'] == 'new-work'


def test_cli_defaults_to_read_only_and_refuses_bad_receipt_without_private_error(packet, tmp_path):
    root, request, *_ = packet
    path = tmp_path / 'receipt.json'
    put(path, request)
    result = subprocess.run([sys.executable, '-m', 'shantytown.refill_reconcile',
                             '--root', str(root), '--receipt', str(path)], capture_output=True, text=True)
    assert result.returncode == 0 and json.loads(result.stdout)['state'] == 'qualified'
    assert rr.read(root / 'refill/state.json')['pending']['worker']
    path.write_text('{"secret-private-body":')
    result = subprocess.run([sys.executable, '-m', 'shantytown.refill_reconcile',
                             '--root', str(root), '--receipt', str(path), '--apply'], capture_output=True, text=True)
    assert result.returncode == 2 and 'secret-private-body' not in result.stdout + result.stderr


@pytest.mark.parametrize('padding', [2_272_787, 2 * rr.MAX_JSON + 1])
def test_large_unrelated_event_before_exact_receipt_is_streamed(packet, padding):
    root, request, _, _, history = packet
    meta, event = history.read_bytes().splitlines(keepends=True)
    unrelated = json.dumps(dict(type='tool_result', output='x' * padding)).encode() + b'\n'
    history.write_bytes(meta + unrelated + event)
    request['line'] = 3
    before = snapshot(root)
    assert rr.reconcile(root, request, now=1100)['state'] == 'qualified'
    assert snapshot(root) == before


def test_oversized_target_receipt_still_refuses_without_writes(packet):
    root, request, _, _, history = packet
    meta, event = history.read_bytes().splitlines(keepends=True)
    event = event.rstrip(b'\n') + b' ' * rr.MAX_JSON + b'\n'
    history.write_bytes(meta + event)
    request['event_sha256'] = hashlib.sha256(event).hexdigest()
    before = snapshot(root)
    with pytest.raises(ValueError):
        rr.reconcile(root, request, apply=True, now=1100)
    assert snapshot(root) == before
