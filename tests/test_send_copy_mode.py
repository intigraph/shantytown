"""st typed into panes in tmux copy-mode and called it delivered — aegis-6jx.

While a person scrolls back in a pane (copy-mode, mode-keys vi), every key st
sends is a copy-mode COMMAND: `/` and `?` open search prompts, `:` a command
prompt, digits set repeat counts, `v` starts a selection, and the trailing Enter
copies and exits the mode. Measured on tmux 3.6 against a throwaway pane on a
private socket: send() returned success, pane_in_mode went 1 -> 0 (the person was
thrown out of their scrollback) and the body never arrived.

Pinned here: a pane in a mode gets ZERO keystrokes from every send path, the mode
is left alone, and a pane that is not in a mode still gets the whole message.
"""
from __future__ import annotations

import pytest

from shantytown import tmux as tmux_mod


class _Tmux:
    """Answers `#{pane_in_mode}` from a script and records every send-keys."""

    def __init__(self, modes):
        # One answer per display-message query, in order; the last one repeats.
        self.modes = list(modes)
        self.calls = []

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        stdout = ""
        if "display-message" in argv:
            stdout = (self.modes.pop(0) if len(self.modes) > 1 else self.modes[0]) + "\n"

        class _R:
            returncode = 0
        _R.stdout = stdout
        return _R()

    def sendkeys(self):
        return [c for c in self.calls if "send-keys" in c]


@pytest.fixture
def tmux(monkeypatch):
    def make(*modes):
        fake = _Tmux(modes)
        monkeypatch.setattr(tmux_mod.subprocess, "run", fake)
        monkeypatch.setattr(tmux_mod.time, "sleep", lambda _s: None)
        monkeypatch.setattr(tmux_mod, "_journal_send", lambda *_a: None)
        return fake
    return make


def test_a_pane_in_copy_mode_gets_no_keystroke_and_no_success(tmux):
    fake = tmux("1")
    with pytest.raises(tmux_mod.PaneInMode):
        tmux_mod.Tmux().send("p", "body with /search ?x :5 v")
    assert fake.sendkeys() == []


def test_the_refusal_is_a_not_delivered_for_every_existing_caller(tmux):
    # Callers catch PaneNotAgent and report NOT DELIVERED; a new base class
    # would escape them as a traceback.
    tmux("1")
    with pytest.raises(tmux_mod.PaneNotAgent):
        tmux_mod.Tmux().send("p", "x")


def test_a_pane_not_in_a_mode_still_gets_the_whole_message(tmux):
    fake = tmux("0")
    tmux_mod.Tmux().send("p", "hello")
    assert [c[-1] for c in fake.sendkeys()] == ["hello", "Enter"]


def test_an_unreadable_mode_does_not_block_delivery(tmux):
    fake = tmux("")
    tmux_mod.Tmux().send("p", "hello")
    assert [c[-1] for c in fake.sendkeys()] == ["hello", "Enter"]


def test_copy_mode_entered_mid_send_stops_before_the_next_chunk_and_the_enter(tmux):
    # First query (before anything) 0, before chunk 2 the person entered the mode.
    fake = tmux("0", "1")
    body = "a" * (tmux_mod._SEND_CHUNK + 10)
    with pytest.raises(tmux_mod.PaneSubmissionUnverified):
        tmux_mod.Tmux().send("p", body)
    keys = [c[-1] for c in fake.sendkeys()]
    assert keys == ["a" * tmux_mod._SEND_CHUNK]
    assert "Enter" not in keys


def test_copy_mode_entered_before_the_enter_withholds_it(tmux):
    fake = tmux("0", "1")
    with pytest.raises(tmux_mod.PaneSubmissionUnverified):
        tmux_mod.Tmux().send("p", "short")
    assert [c[-1] for c in fake.sendkeys()] == ["short"]


def test_control_and_option_keys_are_refused_in_copy_mode(tmux):
    fake = tmux("1")
    with pytest.raises(tmux_mod.PaneInMode):
        tmux_mod.Tmux().control("p", sorted(tmux_mod.CONTROL_KEYS)[0])
    with pytest.raises(tmux_mod.PaneInMode):
        tmux_mod.Tmux().option("p", 1)
    assert fake.sendkeys() == []


def test_the_double_refuses_exactly_like_the_adapter():
    panes = tmux_mod.NullPanes(in_mode=True)
    with pytest.raises(tmux_mod.PaneInMode):
        panes.send("p", "x")
    with pytest.raises(tmux_mod.PaneInMode):
        panes.control("p", sorted(tmux_mod.CONTROL_KEYS)[0])
    with pytest.raises(tmux_mod.PaneInMode):
        panes.option("p", 1)
    assert panes.sent == [] and panes.controls == [] and panes.picked == []


def test_partial_delivery_says_check_then_retry_without_sending_again(tmux):
    fake = tmux("1")
    with pytest.raises(tmux_mod.PaneSubmissionUnverified) as caught:
        tmux_mod.Tmux()._refuse_in_mode("p", sent=1)
    assert "check delivery before retrying" in str(caught.value)
    assert "do not blindly resend" not in str(caught.value)
    assert fake.sendkeys() == []
