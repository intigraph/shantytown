"""Proof that every notify outcome can fire — especially the two that mean
'nobody was told'.

skein convention: a check that has never returned every one of its outcomes is
not a check. Here the outcome under guard is UNCONFIG (3). A notifier with no
transport configured is the classic silent failure: it returns instantly, prints
nothing alarming, and an escalation policy built on it looks healthy for months.
If UNCONFIG cannot be told apart from DELIVERED, the tool is worse than no tool,
because it manufactures confidence.

Stdlib unittest — no pytest, no network. Run: python3 -m unittest
"""
import io
import os
import sys
import unittest

import notify


class Stdin:
    """Pin stdin to a known stream. Any test that exercises the no-positional
    path MUST use this: notify reads stdin when it is not a tty, so an
    unpinned test hangs instead of failing — the worst kind of red."""

    def __init__(self, text: str):
        self.text = text

    def __enter__(self):
        self.saved = sys.stdin
        sys.stdin = io.StringIO(self.text)
        return self

    def __exit__(self, *a):
        sys.stdin = self.saved


class Env:
    """Set exactly the environment under test — and clear everything else, so a
    developer's own NTFY_URL cannot make a test pass that would fail in CI."""

    KEYS = ["NTFY_URL", "NTFY_TOPIC", "NTFY_TOKEN", "NOTIFY_WEBHOOK_URL",
            "NOTIFY_WEBHOOK_KEY", "NOTIFY_MIN_SEVERITY", "NOTIFY_PRIORITY_CRITICAL"]

    def __init__(self, **kw):
        self.kw = kw

    def __enter__(self):
        self.saved = {k: os.environ.get(k) for k in self.KEYS}
        for k in self.KEYS:
            os.environ.pop(k, None)
        os.environ.update(self.kw)
        return self

    def __exit__(self, *a):
        for k in self.KEYS:
            os.environ.pop(k, None)
            if self.saved[k] is not None:
                os.environ[k] = self.saved[k]


class Post:
    """Swap the HTTP layer out. Records every call so we can assert what was
    sent, and to whom."""

    def __init__(self, *responses):
        self.responses = list(responses) or [(200, '{"id":"abc"}')]
        self.calls = []

    def __enter__(self):
        self._post = notify._post

        def fake(url, data, headers):
            self.calls.append((url, data, headers))
            if isinstance(self.responses[0], Exception):
                raise self.responses.pop(0)
            return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]

        notify._post = fake
        return self

    def __exit__(self, *a):
        notify._post = self._post


NTFY = {"NTFY_URL": "https://push.example.com", "NTFY_TOPIC": "ops"}
HOOK = {"NOTIFY_WEBHOOK_URL": "https://chat.example.com/hooks/x"}


class TestNothingSent(unittest.TestCase):
    def test_no_transport_is_UNCONFIG_never_success(self):
        """The whole reason this script exists."""
        with Env(), Post() as p:
            rc = notify.main(["disk full"])
        self.assertEqual(rc, notify.UNCONFIG)
        self.assertNotEqual(rc, notify.DELIVERED)
        self.assertEqual(p.calls, [], "nothing may be sent when nothing is configured")

    def test_half_configured_ntfy_is_still_nothing(self):
        """A topic with no URL is not a transport. Silently skipping it is how a
        typo in one env var becomes an escalation path that never fired."""
        with Env(NTFY_TOPIC="ops"), Post() as p:
            rc = notify.main(["disk full"])
        self.assertEqual(rc, notify.UNCONFIG)
        self.assertEqual(p.calls, [])

    def test_below_min_severity_sends_nothing_and_says_so(self):
        with Env(NOTIFY_MIN_SEVERITY="critical", **NTFY), Post() as p:
            rc = notify.main(["-s", "info", "just fyi"])
        self.assertEqual(rc, notify.UNCONFIG)
        self.assertEqual(p.calls, [])

    def test_empty_message_refused(self):
        # stdin is pinned to an empty stream on purpose: with no positional
        # message and a non-tty stdin, notify reads the body from stdin (that is
        # the documented `... | notify` path). Leaving the real stdin in place
        # would make this test hang waiting for input rather than assert.
        with Env(**NTFY), Post() as p, Stdin(""):
            rc = notify.main([])
        self.assertEqual(rc, notify.UNCONFIG)
        self.assertEqual(p.calls, [])

    def test_body_can_come_from_stdin(self):
        with Env(**NTFY), Post() as p, Stdin("disk 92% on host-b"):
            rc = notify.main([])
        self.assertEqual(rc, notify.DELIVERED)
        self.assertIn(b"disk 92%", p.calls[0][1])


class TestOutcomes(unittest.TestCase):
    def test_all_accepted_is_DELIVERED(self):
        with Env(**NTFY, **HOOK), Post((200, '{"id":"abc"}')):
            rc = notify.main(["-s", "warning", "disk 92%"])
        self.assertEqual(rc, notify.DELIVERED)

    def test_one_of_two_is_PARTIAL(self):
        with Env(**NTFY, **HOOK), Post((200, '{"id":"abc"}'), (404, "no such hook")):
            rc = notify.main(["disk 92%"])
        self.assertEqual(rc, notify.PARTIAL)

    def test_all_failed_is_FAILED_not_unconfigured(self):
        """Configured-and-broken must be distinguishable from never-configured:
        one is an outage, the other is a missing line in your env file."""
        with Env(**NTFY), Post((500, "upstream error")):
            rc = notify.main(["disk 92%"])
        self.assertEqual(rc, notify.FAILED)
        self.assertNotEqual(rc, notify.UNCONFIG)

    def test_unreachable_is_FAILED(self):
        with Env(**NTFY), Post(OSError("connection refused")):
            rc = notify.main(["disk 92%"])
        self.assertEqual(rc, notify.FAILED)

    def test_dry_run_sends_nothing_but_reports_the_plan(self):
        with Env(**NTFY), Post() as p:
            rc = notify.main(["-n", "disk 92%"])
        self.assertEqual(rc, notify.DELIVERED)
        self.assertEqual(p.calls, [], "--dry-run must not touch the network")


class TestPayload(unittest.TestCase):
    def test_severity_maps_to_ntfy_priority(self):
        with Env(**NTFY), Post() as p:
            notify.main(["-s", "critical", "everything is on fire"])
        self.assertEqual(p.calls[0][2]["Priority"], "5")

    def test_priority_map_is_overridable(self):
        with Env(**NTFY, NOTIFY_PRIORITY_CRITICAL="4"), Post() as p:
            notify.main(["-s", "critical", "everything is on fire"])
        self.assertEqual(p.calls[0][2]["Priority"], "4")

    def test_topic_appended_to_url(self):
        with Env(**NTFY), Post() as p:
            notify.main(["hi"])
        self.assertEqual(p.calls[0][0], "https://push.example.com/ops")

    def test_title_header_is_single_line(self):
        """ntfy carries the title in an HTTP header; a newline there is a broken
        request, not a two-line title."""
        with Env(**NTFY), Post() as p:
            notify.main(["-t", "line one\nline two", "body"])
        self.assertNotIn("\n", p.calls[0][2]["Title"])

    def test_webhook_payload_key_is_configurable(self):
        with Env(**HOOK, NOTIFY_WEBHOOK_KEY="content"), Post() as p:
            notify.main(["hello"])
        self.assertIn(b'"content"', p.calls[0][1])

    def test_body_is_sent_verbatim_not_shell_expanded(self):
        """The tool never re-interprets the body. Backticks arrive as backticks."""
        body = "ran `df -h` and $(uptime) said trouble"
        with Env(**NTFY), Post() as p:
            notify.main([body])
        self.assertIn(b"`df -h`", p.calls[0][1])
        self.assertIn(b"$(uptime)", p.calls[0][1])


if __name__ == "__main__":
    unittest.main()
