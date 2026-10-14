#!/usr/bin/env python3
"""Tests for retro_hook.py — the property that matters is ONCE PER SESSION.

A Claude Code Stop hook fires on every turn boundary. These tests assert the hook
fires the retro exactly once per session and is a silent no-op on every other
Stop — and that it never blocks (fails open) when it should stay quiet.

    python3 -m unittest        # from this directory
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "retro_hook.py")


def run_hook(payload: dict, env_extra: dict):
    env = dict(os.environ)
    env.update(env_extra)
    p = subprocess.run(
        [sys.executable, HOOK],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )
    return p


def fires(p) -> bool:
    """A fire = exit 0 AND a block-decision on stdout. Anything else is a no-op."""
    if p.returncode != 0:
        return False
    out = p.stdout.strip()
    if not out:
        return False
    try:
        return json.loads(out).get("decision") == "block"
    except ValueError:
        return False


class TestOncePerSession(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.mkdtemp()
        self.env = {"RETRO_STATE_DIR": self.state, "RETRO_MIN_INTERVAL_HOURS": "0"}

    def test_first_stop_fires(self):
        p = run_hook({"session_id": "s1", "stop_hook_active": False}, self.env)
        self.assertEqual(p.returncode, 0)
        self.assertTrue(fires(p), "first Stop of a session must fire the retro")

    def test_second_stop_same_session_is_silent(self):
        run_hook({"session_id": "s1", "stop_hook_active": False}, self.env)
        p = run_hook({"session_id": "s1", "stop_hook_active": False}, self.env)
        self.assertEqual(p.returncode, 0)
        self.assertFalse(fires(p), "a second Stop in the same session must NOT fire")
        self.assertEqual(p.stdout.strip(), "", "no-op must emit nothing")

    def test_stop_hook_active_never_fires(self):
        # Guard 1: the Stop caused by our own block must not re-fire (no loop).
        p = run_hook({"session_id": "s2", "stop_hook_active": True}, self.env)
        self.assertFalse(fires(p))
        self.assertEqual(p.stdout.strip(), "")

    def test_different_sessions_each_fire_once(self):
        a = run_hook({"session_id": "a", "stop_hook_active": False}, self.env)
        b = run_hook({"session_id": "b", "stop_hook_active": False}, self.env)
        self.assertTrue(fires(a))
        self.assertTrue(fires(b), "a genuinely new session gets its own retro")

    def test_rate_limit_suppresses_new_session(self):
        env = dict(self.env)
        env["RETRO_MIN_INTERVAL_HOURS"] = "6"
        first = run_hook({"session_id": "x", "stop_hook_active": False}, env)
        second = run_hook({"session_id": "y", "stop_hook_active": False}, env)
        self.assertTrue(fires(first))
        self.assertFalse(fires(second), "within the interval, a new session is suppressed")

    def test_missing_session_id_dedups_by_day(self):
        first = run_hook({"stop_hook_active": False}, self.env)
        second = run_hook({"stop_hook_active": False}, self.env)
        self.assertTrue(fires(first), "with no session_id it still fires once")
        self.assertFalse(fires(second), "and de-dups by day rather than every turn")

    def test_disabled_is_silent(self):
        env = dict(self.env)
        env["RETRO_DISABLE"] = "1"
        p = run_hook({"session_id": "z", "stop_hook_active": False}, env)
        self.assertFalse(fires(p))

    def test_malformed_stdin_fails_open(self):
        env = dict(os.environ)
        env.update(self.env)
        p = subprocess.run(
            [sys.executable, HOOK],
            input="this is not json {{{",
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(p.returncode, 0, "bad stdin must never block a stop")
        # It may or may not fire (it de-dups by day), but it must exit 0 cleanly.


class TestDpSignal(unittest.TestCase):
    """The dp (desirepath) input is OPTIONAL and self-hiding: present -> a section
    of pre-identified improvement candidates; absent/broken -> empty, never an
    error. Imported directly since _dp_signal is a pure function of `dp`'s output."""

    def setUp(self):
        sys.path.insert(0, HERE)
        import retro_hook
        self.rh = retro_hook
        original_run = self.rh.subprocess.run
        original_which = self.rh.shutil.which
        self.addCleanup(setattr, self.rh.subprocess, "run", original_run)
        self.addCleanup(setattr, self.rh.shutil, "which", original_which)

    def test_absent_dp_hides(self):
        self.rh.shutil.which = lambda _: None
        self.assertEqual(self.rh._dp_signal(), "")

    def test_present_dp_lists_recurring_calls(self):
        self.rh.shutil.which = lambda _: "/usr/bin/dp"

        class P:
            returncode = 0
            stdout = json.dumps([
                {"pattern": "SomeTool", "count": 9},
                {"pattern": "Other", "count": 2},
            ])

        self.rh.subprocess.run = lambda *a, **k: P()
        out = self.rh._dp_signal()
        self.assertIn("SomeTool (reached for 9x)", out)
        self.assertIn("Other (reached for 2x)", out)

    def test_dp_error_hides(self):
        self.rh.shutil.which = lambda _: "/usr/bin/dp"

        class P:
            returncode = 1
            stdout = ""

        self.rh.subprocess.run = lambda *a, **k: P()
        self.assertEqual(self.rh._dp_signal(), "")

    def test_dp_crash_hides(self):
        self.rh.shutil.which = lambda _: "/usr/bin/dp"

        def boom(*a, **k):
            raise OSError("no dp")

        self.rh.subprocess.run = boom
        self.assertEqual(self.rh._dp_signal(), "")


if __name__ == "__main__":
    unittest.main()
