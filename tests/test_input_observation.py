"""Sanitized Codex 0.161 SGR observations; never send keys or retain bodies."""
import json
import subprocess
from types import SimpleNamespace

import pytest

from shantytown import input_observation as observation, tmux, triage
from test_codex_0161_composer import frame


@pytest.mark.parametrize("body,state,reason", [
    ("fixture notice\n" * 10, triage.INPUT_QUEUED, "typed-composer"),
    ("\x1b[2mghost fixture\x1b[0m", triage.INPUT_PLACEHOLDER, "ghost-composer"),
    ("", triage.INPUT_EMPTY, "empty-composer"),
])
def test_actual_framed_states_are_not_changed(body, state, reason):
    screen = frame(body)
    calls = []
    panes = SimpleNamespace(capture=lambda *a, **kw: calls.append(kw) or screen)
    result = observation.capture(panes, "fixture", wall_clock=lambda: 1000,
                                 monotonic=lambda: 2)
    assert (result["state"], result["reason"]) == (state, reason)
    assert result["state"] == triage.input_state(screen)
    assert result["observed_at"] == 1000
    assert calls == [{"attrs": True, "timeout": 5, "check": True}]
    assert "fixture" not in json.dumps(result)


def test_unknown_and_busy_are_separate_and_text_free():
    for screen in ("› private fixture", "ordinary private output",
                   triage.strip_attrs(frame("private fixture\n" * 10))):
        result = observation.classify(screen, started_at=1, observed_at=2, elapsed_seconds=1)
        assert result["state"] in (triage.INPUT_UNKNOWN, triage.INPUT_ABSENT)
        assert "private" not in json.dumps(result)
    screen = "• Working (12s • esc to interrupt)\n" + frame("fixture queue")
    result = observation.classify(screen, started_at=1, observed_at=2, elapsed_seconds=1)
    assert result["busy"] is True
    assert result["state"] == triage.INPUT_QUEUED


@pytest.mark.parametrize("failure,reason", [
    (subprocess.TimeoutExpired("private command", 5), "capture-timeout"),
    (OSError("private failure"), "capture-failed"),
    (subprocess.CalledProcessError(1, "private command"), "capture-failed"),
])
def test_capture_failures_retain_bounded_why_not_exception_text(failure, reason):
    def fail(*a, **kw):
        raise failure
    result = observation.capture(SimpleNamespace(capture=fail), "fixture")
    assert result["state"] == triage.INPUT_UNKNOWN
    assert result["reason"] == reason
    assert result["busy"] is None
    assert "private" not in json.dumps(result)
    assert result["observed_at"] >= result["started_at"]


@pytest.mark.parametrize("screen,reason", [(None, "invalid-capture"),
                                           ("x" * 131073, "capture-limit")])
def test_incomplete_capture_is_not_empty(screen, reason):
    result = observation.capture(SimpleNamespace(capture=lambda *a, **kw: screen), "fixture")
    assert result["state"] == triage.INPUT_UNKNOWN
    assert result["reason"] == reason


@pytest.mark.parametrize("returncode,screen,state,reason,busy", [
    (0, "", triage.INPUT_ABSENT, "no-composer-frame", False),
    (0, "ordinary output", triage.INPUT_ABSENT, "no-composer-frame", False),
    (1, "", triage.INPUT_UNKNOWN, "capture-failed", None),
    (1, frame("private stale input"), triage.INPUT_UNKNOWN, "capture-failed", None),
])
def test_native_adapter_preserves_capture_outcome(monkeypatch, returncode, screen,
                                                 state, reason, busy):
    calls = []

    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, returncode, stdout=screen,
                                           stderr="private adapter detail")

    monkeypatch.setattr(tmux.subprocess, "run", run)
    result = observation.capture(tmux.Tmux(socket="offline-fixture"), "offline-pane")
    assert (result["state"], result["reason"], result["busy"]) == (state, reason, busy)
    assert len(calls) == 1
    cmd, kwargs = calls[0]
    assert "capture-pane" in cmd and "-e" in cmd
    assert "send-keys" not in cmd
    assert kwargs == {"capture_output": True, "text": True, "timeout": 5}
    assert "private" not in json.dumps(result) and "offline-pane" not in json.dumps(result)


def test_native_timeout_and_default_capture_contract(monkeypatch):
    panes = tmux.Tmux(socket="offline-fixture")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(tmux.subprocess, "run", lambda cmd, **kw:
                      subprocess.CompletedProcess(cmd, 1, stdout="", stderr="private"))
        assert panes.capture("offline-pane") == ""
        with pytest.raises(subprocess.CalledProcessError):
            panes.capture("offline-pane", check=True)

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("private adapter detail", 5)

    monkeypatch.setattr(tmux.subprocess, "run", timeout)
    result = observation.capture(panes, "offline-pane")
    assert (result["state"], result["reason"], result["busy"]) == (
        triage.INPUT_UNKNOWN, "capture-timeout", None)
    assert "private" not in json.dumps(result)


def test_offline_panes_support_checked_capture():
    result = observation.capture(tmux.NullPanes(screen="ordinary output"), "offline-pane")
    assert (result["state"], result["reason"]) == (triage.INPUT_ABSENT, "no-composer-frame")
