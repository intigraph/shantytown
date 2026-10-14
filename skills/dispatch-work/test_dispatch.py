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
        self._e, self._c, self._m = d.pane_exists, d.pane_capture, d.pane_in_mode
        d.pane_exists = lambda t: self.screen is not None
        d.pane_capture = lambda t: self.screen or ""
        d.pane_in_mode = lambda t: False
        return self

    def __exit__(self, *a):
        d.pane_exists, d.pane_capture, d.pane_in_mode = self._e, self._c, self._m


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

    def _swap(self, exists, capture, send, in_mode=lambda t: False):
        self._e, self._c, self._s, self._m = d.pane_exists, d.pane_capture, d.pane_send, d.pane_in_mode
        d.pane_exists, d.pane_capture, d.pane_send, d.pane_in_mode = exists, capture, send, in_mode

    def _restore(self):
        d.pane_exists, d.pane_capture, d.pane_send, d.pane_in_mode = self._e, self._c, self._s, self._m

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


class TestNoShellInjection(unittest.TestCase):
    """A title or id is DATA. Reproduced before the fix: `$(...)` in a title ran."""
    PAYLOADS = ["$(echo PWNED-BY-TITLE)", "`echo PWNED-BY-BACKTICK`", 'quote " and $HOME']

    def test_create_cmd_passes_payloads_through_literally(self):
        import os, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "seen")
            for payload in self.PAYLOADS:
                item = d.create_cmd(payload, 'printf "%s" "{title}" > ' + out + '; echo item-9')
                self.assertEqual(item, "item-9")
                with open(out) as f:
                    self.assertEqual(f.read(), payload)

    def test_open_check_id_is_not_executed(self):
        import os, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            marker = os.path.join(tmp, "ran")
            cmd, env = d.shell_template('test "{id}" = "$EXPECT"', id=f"$(touch {marker})")
            env["EXPECT"] = f"$(touch {marker})"
            import subprocess
            r = subprocess.run(cmd, shell=True, env=env)
            self.assertEqual(r.returncode, 0)          # compared as text
            self.assertFalse(os.path.exists(marker))   # and never executed


class FakeTmux:
    """Records every tmux call; answers #{pane_in_mode} with `mode`."""
    def __init__(self, mode="1", rc=0):
        self.mode, self.rc, self.calls = mode, rc, []

    def __call__(self, *args):
        import subprocess
        self.calls.append(args)
        if args[0] == "display-message":
            return subprocess.CompletedProcess(args, self.rc, self.mode + "\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    def sends(self):
        return [c for c in self.calls if c[0] == "send-keys"]


class TestCopyModeRefusal(unittest.TestCase):
    """The copy-mode trap (seen on this fleet the same day): typed text becomes
    vi copy-mode commands and the human scrolling back is stuck."""
    def _with(self, fake):
        self._t = d._tmux
        d._tmux = fake
        self.addCleanup(lambda: setattr(d, "_tmux", self._t))

    def test_pane_send_in_copy_mode_sends_zero_keys(self):
        fake = FakeTmux("1")
        self._with(fake)
        with self.assertRaises(RuntimeError):
            d.pane_send("x:0.0", "hello")
        self.assertEqual(fake.sends(), [])

    def test_unreadable_mode_also_sends_nothing(self):
        fake = FakeTmux("", rc=1)
        self._with(fake)
        with self.assertRaises(RuntimeError):
            d.pane_send("x:0.0", "hello")
        self.assertEqual(fake.sends(), [])

    def test_normal_mode_still_sends(self):
        fake = FakeTmux("0")
        self._with(fake)
        d.pane_send("x:0.0", "hello")
        self.assertEqual(len(fake.sends()), 2)

    def test_triage_refuses_a_pane_in_copy_mode(self):
        fake = FakeTmux("1")
        self._with(fake)
        decision = d.triage("x:0.0", "deploy")
        self.assertIs(decision.action, d.Action.REFUSE)
        self.assertEqual(decision.inputs["pane_in_mode"], True)

    def test_dispatch_refuses_end_to_end_with_zero_send_keys(self):
        fake = FakeTmux("1")
        self._with(fake)
        rc = d.main(["send", "x:0.0", "item-1"])
        self.assertEqual(rc, 3)
        self.assertEqual(fake.sends(), [])


if __name__ == "__main__":
    unittest.main()
