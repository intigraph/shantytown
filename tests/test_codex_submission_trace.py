import json
import stat

import pytest

from shantytown import codex_submission_trace as trace, tmux
from test_codex_submission import BODY, READY, OWNED, BUSY, FOOTER, transport, keys


def read(root):
    path, = (root / 'ephemeral').glob('*.submission-*.jsonl')
    return path, [json.loads(line) for line in path.read_text().splitlines()]


@pytest.mark.parametrize('observed', [True, False])
def test_launch_retains_ordered_frames_without_changing_keys(tmp_path, monkeypatch, observed):
    panes, calls = transport(monkeypatch, [READY])
    panes.delivery_root = tmp_path
    monkeypatch.setattr(panes, '_codex_native_probe', lambda *_: None)
    clipped = '› clipped body tail\n\n' + FOOTER
    def capture(*args, **kwargs):
        sent = keys(calls)
        if not any('-l' in call for call in sent):
            return READY
        if not any(call[-1] == 'Enter' for call in sent):
            return OWNED
        return BUSY if observed else clipped
    monkeypatch.setattr(panes, 'capture', capture)
    if observed:
        assert panes._send('st-eph-task-abc123', BODY).matches('st-eph-task-abc123', BODY)
    else:
        with pytest.raises(tmux.PaneSubmissionUnverified):
            panes._send('st-eph-task-abc123', BODY)
    path, rows = read(tmp_path)
    assert [r['stage'] for r in rows] == list(trace.STAGES)
    assert rows[0]['screen'] == OWNED
    assert rows[1]['key'] == 'Enter'
    assert rows[2]['outcome'] == ('observed' if observed else 'unverified')
    assert all(r['at'].endswith('+00:00') for r in rows)
    assert [r['monotonic_ns'] for r in rows] == sorted(r['monotonic_ns'] for r in rows)
    assert all(r['capture_finished_monotonic_ns'] >= r['monotonic_ns'] for r in rows)
    assert len({r['body_sha256'] for r in rows}) == 1
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert [c[-1] for c in keys(calls) if '-l' in c] == [BODY]
    assert [c[-1] for c in keys(calls) if '-l' not in c] == ['Enter']


@pytest.mark.parametrize('character', ['x', '🙂'])
def test_frames_are_bounded_and_duplicate_stages_do_not_append(tmp_path, character):
    t = trace.for_launch(tmp_path, 'st-eph-task-abc123', BODY)
    for _ in range(2):
        for stage in trace.STAGES:
            t.capture(stage, lambda *a, **k: character * (trace.CAPTURE_BYTES + 100))
    _, rows = read(tmp_path)
    assert len(rows) == 3
    assert all(r['truncated'] and len(r['screen'].encode()) <= trace.CAPTURE_BYTES for r in rows)


def test_capture_and_storage_errors_do_not_change_delivery(tmp_path, capsys):
    t = trace.for_launch(tmp_path, 'st-eph-task-abc123', BODY)
    def fail(*args, **kwargs):
        raise TimeoutError('private details must not enter diagnostics')
    t.capture('paste-end', fail)
    path, rows = read(tmp_path)
    assert rows[0]['capture_error'] == 'TimeoutError' and 'screen' not in rows[0]
    # A replaced file must not receive any captured pane content.
    path.unlink()
    target = tmp_path / 'target'
    target.write_text('untouched')
    path.symlink_to(target)
    t.capture('enter-sent', lambda *a, **k: 'sensitive pane')
    assert target.read_text() == 'untouched'
    assert 'not retained (OSError)' in capsys.readouterr().err


def test_only_launch_panes_collect_screens(tmp_path):
    assert trace.for_launch(None, 'st-eph-task-abc123', BODY) is None
    assert trace.for_launch(tmp_path, 'st-worker', BODY) is None
    assert trace.for_launch(tmp_path, 'st-eph-task-../../foreign', BODY) is None


def test_storage_failure_does_not_mask_success_or_add_a_key(tmp_path, monkeypatch, capsys):
    panes, calls = transport(monkeypatch, [READY])
    panes.delivery_root = tmp_path
    (tmp_path / 'ephemeral').write_text('directory unavailable')
    monkeypatch.setattr(panes, '_codex_native_probe', lambda *_: None)
    def capture(*args, **kwargs):
        if any(c[-1] == 'Enter' for c in keys(calls)):
            return BUSY
        return OWNED if keys(calls) else READY
    monkeypatch.setattr(panes, 'capture', capture)
    assert panes._send('st-eph-task-abc123', BODY).matches('st-eph-task-abc123', BODY)
    assert len(keys(calls)) == 2
    assert capsys.readouterr().err.count('not retained') == 3
