"""Natural scheduled receipts wake reassessment without cycling or claiming acceptance."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from shantytown import resume_events, resume_idle_cycle as idle, triage

NOW = datetime(2026, 11, 10, 10, tzinfo=timezone.utc)
BINDING = resume_events.REGISTRY['natural-idle-cycle-v1']
BOOT = 'a' * 32
REQUEST = {'auto': True, 'requested_at': NOW.timestamp() - 60,
           'checkpoint_bead': 'project-checkpoint'}
READING = SimpleNamespace(state=triage.IDLE, depth_k=500)


def row():
    return {'MESSAGE': idle.receipt(REQUEST, 'worker', READING, 0),
            '_SYSTEMD_USER_UNIT': idle.UNIT, '_UID': '1000', '_BOOT_ID': BOOT,
            '_SYSTEMD_INVOCATION_ID': 'b' * 32,
            '__REALTIME_TIMESTAMP': str(int((NOW.timestamp() - 1) * 1e6)),
            '__CURSOR': 'native-cursor'}


def decide(rows):
    return idle.decide(b'\n'.join(json.dumps(r).encode() for r in rows),
                       BINDING, NOW, uid=1000, boot=BOOT)


def test_exact_native_scheduled_receipt_wakes_only_owner_reassessment():
    result = decide([row()])
    assert result.state == 'MET' and result.events == ('native-cursor',)
    assert 'acceptance still owed' in result.reason
    assert len(result.digest) == 64


@pytest.mark.parametrize('change', [
    {'auto': False}, {'auto': 1}, {'runtime_update': {'version': 'next'}},
    {'checkpoint_bead': ''}, {'checkpoint_bead': '../secret'},
    {'requested_at': float('nan')}, {'requested_at': True},
])
def test_ineligible_request_never_emits(change):
    assert idle.receipt(REQUEST | change, 'worker', READING, 0) is None


@pytest.mark.parametrize('reading,result', [
    (None, 0), (READING, 2),
    (SimpleNamespace(state=triage.BUSY, depth_k=500), 0),
    (SimpleNamespace(state=triage.IDLE, depth_k=None), 0),
    (SimpleNamespace(state=triage.IDLE, depth_k=float('inf')), 0),
    (SimpleNamespace(state=triage.IDLE, depth_k=399), 0),
])
def test_refused_busy_shallow_or_unknown_is_not_completion(reading, result):
    assert idle.receipt(REQUEST, 'worker', reading, result) is None


@pytest.mark.parametrize('key,value', [
    ('_SYSTEMD_USER_UNIT', 'unrelated.service'), ('_UID', '1001'),
    ('_BOOT_ID', 'c' * 32), ('_SYSTEMD_INVOCATION_ID', ''),
    ('__REALTIME_TIMESTAMP', '0'), ('__CURSOR', ''), ('MESSAGE', 'plain output'),
    ('MESSAGE', 42),
])
def test_foreign_or_incomplete_native_identity_is_unknown(key, value):
    evidence = row(); evidence[key] = value
    assert decide([evidence]).state == 'UNKNOWN'


@pytest.mark.parametrize('key,value', [
    ('schema', True), ('producer', 'manual'), ('origin', 'manual'),
    ('result', 'requested'), ('context_before_k', 0),
    ('context_before_k', float('nan')), ('requested_at', NOW.timestamp() + 1),
    ('checkpoint_item', ''), ('agent', '../worker'),
])
def test_queued_manual_shallow_or_invalid_body_is_unknown(key, value):
    evidence = row()
    body = json.loads(evidence['MESSAGE'][len(idle.PREFIX):]); body[key] = value
    evidence['MESSAGE'] = idle.PREFIX + json.dumps(body)
    assert decide([evidence]).state == 'UNKNOWN'


def test_retention_gaps_and_caps_do_not_claim_absence():
    assert decide([]).state == 'UNKNOWN'
    assert decide([row()] * 101).state == 'UNKNOWN'
    assert idle.decide(b'x' * (idle.MAX_BYTES + 1), BINDING, NOW,
                       uid=1000, boot=BOOT).state == 'UNKNOWN'
    assert idle.decide(b'{', BINDING, NOW, uid=1000, boot=BOOT).state == 'UNKNOWN'


def test_duplicate_fields_and_partial_bad_evidence_never_promote():
    raw = json.dumps(row()).replace('"_UID": "1000"', '"_UID": "1000", "_UID": "1000"')
    assert idle.decide(raw.encode(), BINDING, NOW, uid=1000, boot=BOOT).state == 'UNKNOWN'
    assert decide([row(), {}]).state == 'UNKNOWN'


def test_registry_is_source_owned_and_old_protected_binding_stays_disabled(monkeypatch):
    with pytest.raises(ValueError):
        resume_events.binding_for('natural-idle-cycle-v1', 'other-item')
    with pytest.raises(ValueError):
        resume_events.binding_for('protected-recycle-v1', 'aegis-67p0lj')
    calls = []
    monkeypatch.setattr(idle, 'evaluate', lambda binding, now: calls.append(binding) or
                        resume_events.Verdict('UNKNOWN', 'fixture journal unavailable'))
    assert resume_events.evaluate('natural-idle-cycle-v1', 'aegis-zl7jwm', NOW).state == 'UNKNOWN'
    assert calls == [BINDING]


def test_emit_has_no_side_effect_beyond_passive_structured_output(capsys):
    idle.emit(REQUEST, 'worker', READING, 2)
    assert capsys.readouterr().err == ''
    idle.emit(REQUEST, 'worker', READING, 0)
    assert decide([row() | {'MESSAGE': capsys.readouterr().err.strip()}]).state == 'MET'


@pytest.mark.parametrize('auto,runtime_update,result,expected', [
    (True, None, 0, True), (True, None, 2, False),
    (False, None, 0, False), (True, {'fingerprint': 'next'}, 0, False),
])
def test_actual_tend_wrapper_emits_only_after_existing_success_path(
        tmp_path, monkeypatch, capsys, auto, runtime_update, result, expected):
    from shantytown import cli, cycle, notify
    from test_tend import _roster, _Panes, _Args, IDLE
    root = _roster(tmp_path, {'worker': {'role': 'worker', 'pane': 'p-worker'}})
    monkeypatch.setattr(cli, 'Tmux', lambda *_a, **_k: _Panes(screens={'p-worker': IDLE}))
    monkeypatch.setattr(notify, 'agent_states', lambda *_a, **_k: {'worker': READING})
    monkeypatch.setattr(cli, '_TEND_SWEEP_BUDGET_S', 120)
    requests = cycle.Requests(root)
    requests.request('worker', 'saved fixture checkpoint', auto=auto,
                     checkpoint_bead='project-checkpoint', runtime_update=runtime_update)
    calls = []
    monkeypatch.setattr(cli, '_serve_cycle_request', lambda *args: calls.append(args) or result)
    cli._tend_once(_Args(root))
    output = capsys.readouterr().err
    assert (idle.PREFIX in output) is expected
    assert len(calls) == 1  # receipt observation never requests a second cycle


@pytest.mark.parametrize('mode,expected', [('receipt', 'MET'), ('failed', 'UNKNOWN'), ('oversized', 'UNKNOWN')])
def test_native_reader_bounds_real_subprocess_output(tmp_path, monkeypatch, mode, expected):
    import os
    import subprocess
    import sys
    original = subprocess.Popen
    evidence = row()
    evidence['_UID'] = str(os.getuid())
    evidence['_BOOT_ID'] = idle.Path('/proc/sys/kernel/random/boot_id').read_text().strip().replace('-', '')
    path = tmp_path / 'journal.json'
    path.write_text(json.dumps(evidence) + '\n')
    commands = []

    def fixture_process(argv, **kwargs):
        commands.append(argv)
        if mode == 'receipt':
            script = 'import pathlib,sys; sys.stdout.buffer.write(pathlib.Path(sys.argv[1]).read_bytes())'
        elif mode == 'oversized':
            script = 'import sys; sys.stdout.buffer.write(b"x" * (1024 * 1024 + 10))'
        else:
            script = 'raise SystemExit(2)'
        return original([sys.executable, '-c', script, str(path)], **kwargs)

    monkeypatch.setattr(idle.subprocess, 'Popen', fixture_process)
    assert idle.evaluate(BINDING, NOW).state == expected
    assert len(commands) == 1
    assert commands[0][:4] == ['journalctl', '--user', '--unit', idle.UNIT]
    assert commands[0][commands[0].index('-n') + 1] == '101'
    assert '--boot=0' in commands[0]
