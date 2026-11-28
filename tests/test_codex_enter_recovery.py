"""Experimental launch recovery needs a retained, exact owned composer."""
import json

import pytest

from shantytown import tmux
from test_codex_submission import BODY, READY, OWNED, BUSY, FOOTER, transport, keys


def launch(tmp_path, monkeypatch, frame=OWNED, recover=True):
    panes, calls = transport(monkeypatch, [READY])
    panes.delivery_root = tmp_path
    monkeypatch.setattr(panes, '_codex_native_probe', lambda *_: None)
    def capture(*args, **kwargs):
        sent = keys(calls)
        if not any('-l' in c for c in sent):
            return READY
        enters = sum(c[-1] == 'Enter' for c in sent)
        if not enters:
            return OWNED
        return BUSY if recover and enters >= 2 else frame
    monkeypatch.setattr(panes, 'capture', capture)
    return panes, calls


def test_exact_owned_capture_recovers_once_without_resending_body(tmp_path, monkeypatch):
    monkeypatch.setenv('SHANTY_CODEX_ENTER_RETRY', '1')
    panes, calls = launch(tmp_path, monkeypatch)
    assert panes._send('st-eph-task-abc123', BODY).matches('st-eph-task-abc123', BODY)
    assert [c[-1] for c in keys(calls)] == [BODY, 'Enter', 'Enter']
    path, = (tmp_path / 'ephemeral').glob('*.jsonl')
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [r['stage'] for r in rows] == [
        'paste-end', 'enter-sent', 'retry-check', 'retry-enter-sent', 'verify']
    assert rows[2]['screen'] == OWNED
    assert rows[3]['key'] == 'Enter'
    assert rows[4]['outcome'] == 'observed'


@pytest.mark.parametrize('flag', [None, '', '0', 'true', 'unknown'])
def test_default_off_and_invalid_flags_never_retry(tmp_path, monkeypatch, flag):
    if flag is None:
        monkeypatch.delenv('SHANTY_CODEX_ENTER_RETRY', raising=False)
    else:
        monkeypatch.setenv('SHANTY_CODEX_ENTER_RETRY', flag)
    panes, calls = launch(tmp_path, monkeypatch)
    with pytest.raises(tmux.PaneSubmissionUnverified):
        panes._send('st-eph-task-abc123', BODY)
    assert [c[-1] for c in keys(calls)] == [BODY, 'Enter']


@pytest.mark.parametrize('frame', [
    READY, BUSY, OWNED.replace(BODY, 'someone else'),
    '› [Pasted Content 45 chars]\n' + FOOTER,
    '› body tail\n' + FOOTER,
    'Working (1s • esc to interrupt)\n' + OWNED,
    '• Queued follow-up inputs\n  ↳ pending\n' + OWNED,
])
def test_other_states_never_authorize_extra_enter(tmp_path, monkeypatch, frame):
    monkeypatch.setenv('SHANTY_CODEX_ENTER_RETRY', '1')
    panes, calls = launch(tmp_path, monkeypatch, frame, recover=False)
    try:
        panes._send('st-eph-task-abc123', BODY)
    except tmux.PaneSubmissionUnverified:
        pass
    assert [c[-1] for c in keys(calls)] == [BODY, 'Enter']


def test_persistent_owned_body_gets_only_one_retry(tmp_path, monkeypatch):
    monkeypatch.setenv('SHANTY_CODEX_ENTER_RETRY', '1')
    monkeypatch.setattr(tmux, '_CODEX_ATTEMPTS', 10)
    panes, calls = launch(tmp_path, monkeypatch, recover=False)
    monkeypatch.setattr(tmux, '_CODEX_ATTEMPTS', 10)
    with pytest.raises(tmux.PaneSubmissionUnverified):
        panes._send('st-eph-task-abc123', BODY)
    assert [c[-1] for c in keys(calls)] == [BODY, 'Enter', 'Enter']


def test_unretained_check_cannot_authorize_enter(tmp_path, monkeypatch):
    from shantytown.codex_submission_trace import Trace
    monkeypatch.setenv('SHANTY_CODEX_ENTER_RETRY', '1')
    panes, calls = launch(tmp_path, monkeypatch)
    original = Trace.capture
    def capture(self, stage, *args, **kwargs):
        if stage == 'retry-check':
            return None
        return original(self, stage, *args, **kwargs)
    monkeypatch.setattr(Trace, 'capture', capture)
    with pytest.raises(tmux.PaneSubmissionUnverified):
        panes._send('st-eph-task-abc123', BODY)
    assert [c[-1] for c in keys(calls)] == [BODY, 'Enter']


@pytest.mark.parametrize('bad', ['capture-error', 'truncated', 'foreign', 'identity'])
def test_final_retry_evidence_is_checked_again(tmp_path, monkeypatch, bad):
    from shantytown.codex_submission_trace import Trace
    monkeypatch.setenv('SHANTY_CODEX_ENTER_RETRY', '1')
    panes, calls = launch(tmp_path, monkeypatch)
    original = Trace.capture
    def capture(self, stage, *args, **kwargs):
        if stage != 'retry-check':
            return original(self, stage, *args, **kwargs)
        if bad == 'capture-error':
            def fail(*a, **k):
                raise TimeoutError()
            return original(self, stage, fail)
        if bad == 'truncated':
            return original(self, stage, lambda *a, **k: 'x' * 20000 + OWNED)
        if bad == 'foreign':
            return original(self, stage, lambda *a, **k: OWNED.replace(BODY, 'foreign'))
        row = original(self, stage, *args, **kwargs)
        monkeypatch.setattr(panes, 'foreground', lambda _: None)
        return row
    monkeypatch.setattr(Trace, 'capture', capture)
    with pytest.raises(tmux.PaneSubmissionUnverified):
        panes._send('st-eph-task-abc123', BODY)
    assert [c[-1] for c in keys(calls)] == [BODY, 'Enter']


def test_retry_key_error_is_retained_and_never_retried(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.setenv('SHANTY_CODEX_ENTER_RETRY', '1')
    panes, calls = launch(tmp_path, monkeypatch)
    def run(args, **kwargs):
        calls.append(args)
        if args[-1] == 'Enter' and sum(c[-1] == 'Enter' for c in keys(calls)) == 2:
            raise subprocess.CalledProcessError(1, args)
    monkeypatch.setattr(tmux.subprocess, 'run', run)
    with pytest.raises(subprocess.CalledProcessError):
        panes._send('st-eph-task-abc123', BODY)
    path, = (tmp_path / 'ephemeral').glob('*.jsonl')
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    retry, = [r for r in rows if r['stage'] == 'retry-enter-sent']
    assert retry['key'] == 'Enter' and retry['outcome'] == 'key-error'
    assert rows[-1]['stage'] == 'verify' and rows[-1]['outcome'] == 'unverified'
    assert [c[-1] for c in keys(calls)] == [BODY, 'Enter', 'Enter']
