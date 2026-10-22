"""Initial busy-pane submission: exact ownership, fresh state, no blind Enter."""
import subprocess

import pytest

from shantytown import tmux


BODY = 'Private busy first-key control.'
FOOTER = '\n\x1b[2mGPT-6.1\x1b[0m\n\x1b[1m? for shortcuts\x1b[0m\n'
READY = '\x1b[1m›\x1b[0m \x1b[2mAsk Codex\x1b[0m' + FOOTER
OWNED = '\x1b[1m›\x1b[0m ' + BODY + FOOTER
BUSY = 'Working (esc to interrupt)\n' + READY
BUSY_OWNED = 'Working (esc to interrupt)\n' + OWNED
QUEUED = ('Working (esc to interrupt)\nMessages to be submitted after next tool call\n'
          '  ↳ ' + BODY + '\n' + READY)


def transport(monkeypatch, frames):
    pane = tmux.Tmux()
    calls = []
    frames = iter(frames)
    last = ['']

    def capture(*_args, **_kw):
        last[0] = next(frames, last[0])
        if isinstance(last[0], Exception):
            raise last[0]
        return last[0]

    monkeypatch.setattr(pane, 'capture', capture)
    monkeypatch.setattr(pane, 'foreground', lambda _: 'codex')
    monkeypatch.setattr(pane, '_refuse_in_mode', lambda *_a, **_kw: None)
    monkeypatch.setattr(tmux, '_journal_send', lambda *_: None)
    monkeypatch.setattr(tmux, '_CODEX_POLLS', 2)
    monkeypatch.setattr(tmux.time, 'sleep', lambda _: None)
    monkeypatch.setattr(tmux.subprocess, 'run', lambda argv, **kw: calls.append(argv))
    return pane, calls


def submit_keys(calls):
    return [c[-1] for c in calls if 'send-keys' in c and '-l' not in c]


def test_initial_busy_body_queues_with_tab_without_an_enter_or_retype(monkeypatch):
    pane, calls = transport(monkeypatch, [BUSY, BUSY_OWNED, QUEUED])
    with pytest.raises(tmux.PaneSubmissionUnverified, match='queued'):
        pane._send('private-fixture', BODY)
    assert submit_keys(calls) == ['Tab']
    assert [c[-1] for c in calls if '-l' in c] == [BODY]


def test_busy_to_idle_transition_uses_enter_and_observes_the_new_turn(monkeypatch):
    pane, calls = transport(monkeypatch, [BUSY, OWNED, BUSY])
    pane._send('private-fixture', BODY)
    assert submit_keys(calls) == ['Enter']


@pytest.mark.parametrize('fresh', [
    BUSY,
    BUSY_OWNED.replace(BODY, 'Unrelated operator input'),
    BUSY_OWNED.replace(BODY, BODY + ' foreign suffix'),
    BUSY_OWNED.replace(BODY, '[Pasted Content 1234 chars]'),
    OSError('capture unavailable'),
    subprocess.TimeoutExpired('tmux', 2),
])
def test_unowned_or_unreadable_fresh_composer_never_authorizes_a_key(monkeypatch, fresh):
    pane, calls = transport(monkeypatch, [BUSY, fresh])
    with pytest.raises(tmux.PaneSubmissionUnverified):
        pane._send('private-fixture', BODY)
    assert submit_keys(calls) == []


@pytest.mark.parametrize('foreground', [None, 'bash', 'claude', 'node'])
def test_changed_runtime_never_authorizes_initial_tab(monkeypatch, foreground):
    pane, calls = transport(monkeypatch, [BUSY, BUSY_OWNED])
    values = iter(['codex', foreground])
    monkeypatch.setattr(pane, 'foreground', lambda _: next(values))
    monkeypatch.setattr(pane, 'cmdline', lambda _: None)
    with pytest.raises(tmux.PaneSubmissionUnverified):
        pane._send('private-fixture', BODY)
    assert submit_keys(calls) == []


def test_copy_mode_entered_during_settle_blocks_initial_tab(monkeypatch):
    pane, calls = transport(monkeypatch, [BUSY, BUSY_OWNED])
    checks = []

    def refuse(*_a, **_kw):
        checks.append(True)
        if len(checks) == 3:
            raise RuntimeError('private copy-mode control')

    monkeypatch.setattr(pane, '_refuse_in_mode', refuse)
    with pytest.raises(RuntimeError, match='copy-mode control'):
        pane._send('private-fixture', BODY)
    assert submit_keys(calls) == []


@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize("still_busy", [False, True])
def test_owned_busy_quote_is_not_runtime_chrome(monkeypatch, wrapped, still_busy):
    body = "Please report whether Working (esc to interrupt) appears."
    rendered = body.replace("Working", "\n  Working") if wrapped else body
    owned = "\x1b[1m›\x1b[0m " + rendered + FOOTER
    fresh = ("Working (esc to interrupt)\n" if still_busy else "") + owned
    queued = ("Working (esc to interrupt)\n"
              "Messages to be submitted after next tool call\n  ↳ " + body + "\n" + READY)
    pane, calls = transport(monkeypatch, [BUSY, fresh, queued if still_busy else BUSY])
    if still_busy:
        with pytest.raises(tmux.PaneSubmissionUnverified, match="queued"):
            pane._send("private-fixture", body)
    else:
        pane._send("private-fixture", body)
    assert submit_keys(calls) == ["Tab" if still_busy else "Enter"]


def test_owned_retry_ignores_quote_after_busy_turn_ends(monkeypatch):
    body = "Please report whether Working (esc to interrupt) appears."
    owned = "\x1b[1m›\x1b[0m " + body + FOOTER
    pane, calls = transport(monkeypatch, [owned, owned, owned, owned, BUSY])
    pane.submit_owned("private-fixture", body)
    assert submit_keys(calls) == ["Enter"]
