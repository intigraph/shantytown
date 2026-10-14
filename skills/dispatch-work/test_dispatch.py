"""Proof that each triage outcome can fire, and that the safe orderings hold.

skein convention: a check that has never returned every one of its outcomes is
not a check. These tests exist to make each Action reachable on purpose, and to
pin the two subtleties that are easy to get wrong (tail-only marker scanning, and
"high context but related" NOT clearing).

Stdlib unittest — no pytest, no network, no real tmux. Run: python3 -m unittest
"""
import unittest

import dispatch as d


class Screen:
    """Swap tmux out for a canned screen, so triage is a pure function of text."""
    def __init__(self, screen: str | None):
        self.screen = screen

    def __enter__(self):
        self._e, self._c = d.pane_exists, d.pane_capture
        d.pane_exists = lambda t: self.screen is not None
        d.pane_capture = lambda t: self.screen or ""
        return self

    def __exit__(self, *a):
        d.pane_exists, d.pane_capture = self._e, self._c


class TestTriageOutcomes(unittest.TestCase):
    def _act(self, screen, work="deploy the ingress controller"):
        with Screen(screen):
            return d.triage("x:0.0", work).action

    def test_no_session_restarts(self):
        self.assertIs(self._act(None), d.Action.RESTART)

    def test_wedged_restarts(self):
        self.assertIs(self._act("done\n[Process completed]"), d.Action.RESTART)

    def test_in_flight_refuses(self):
        self.assertIs(self._act("thinking\nesc to interrupt"), d.Action.REFUSE)

    def test_high_context_unrelated_clears(self):
        self.assertIs(
            self._act("a long banana pancake recipe\n/clear to save 737.6k tokens"),
            d.Action.CLEAR,
        )

    def test_high_context_related_nudges(self):
        # The big context IS the new work — clearing would throw away what we want.
        self.assertIs(
            self._act("deploy ingress controller notes\n/clear to save 737.6k tokens",
                      work="deploy the ingress controller"),
            d.Action.NUDGE,
        )

    def test_healthy_nudges(self):
        self.assertIs(self._act("idle\n> "), d.Action.NUDGE)

    def test_traceback_is_not_a_wedge(self):
        # Agents print tracebacks constantly; a printed error is not a dead session.
        self.assertIs(
            self._act("ZeroDivisionError: division by zero\nI'll fix that now\n> "),
            d.Action.NUDGE,
        )

    def test_marker_in_scrollback_does_not_trip(self):
        # "esc to interrupt" 20 lines up is the agent TALKING about a state, not in
        # it. Only the tail is judged.
        old = "esc to interrupt\n" + "\n".join(f"l{i}" for i in range(20)) + "\n> idle"
        self.assertIs(self._act(old), d.Action.NUDGE)

    def test_decision_is_inspectable(self):
        with Screen("idle\n> "):
            dec = d.triage("x:0.0", "deploy")
        self.assertIn("pane", dec.inputs)  # every decision names what it judged on


class TestOpenCheckGuard(unittest.TestCase):
    """The dispatch MESSAGE outlives the item's STATE, so a finished item keeps
    getting dispatched unless something checks. `--open-check` is that check; these
    prove it fires (refuse) and, as a control, that an open item still passes."""

    def _swap(self, exists, capture, send):
        self._e, self._c, self._s = d.pane_exists, d.pane_capture, d.pane_send
        d.pane_exists, d.pane_capture, d.pane_send = exists, capture, send

    def _restore(self):
        d.pane_exists, d.pane_capture, d.pane_send = self._e, self._c, self._s

    def test_closed_item_refuses_before_touching_the_pane(self):
        touched = []
        self._swap(lambda t: touched.append("exists") or True,
                   lambda t: touched.append("capture") or "> ",
                   lambda t, x: touched.append("send"))
        try:
            rc = d.main(["send", "x:0.0", "item-1", "--open-check", "false"])
        finally:
            self._restore()
        self.assertEqual(rc, 3)                 # refused
        self.assertEqual(touched, [])           # and never looked at the pane

    def test_open_item_passes_the_guard(self):
        sent = []
        self._swap(lambda t: True,
                   lambda t: "idle\n> item-1",  # id present -> send confirms
                   lambda t, x: sent.append(x))
        try:
            rc = d.main(["send", "x:0.0", "item-1", "--open-check", "true"])
        finally:
            self._restore()
        self.assertEqual(rc, 0)                 # delivered
        self.assertTrue(sent)                   # the guard did not block a live item


if __name__ == "__main__":
    unittest.main()
