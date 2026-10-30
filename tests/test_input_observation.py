"""Sanitized Codex 0.161 SGR observations; never send keys or retain bodies."""
import json
import subprocess
from types import SimpleNamespace

import pytest

from shantytown import input_observation as observation, triage
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
    assert calls == [{"attrs": True, "timeout": 5}]
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
