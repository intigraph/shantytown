"""A met resume gate releases a hold, never a previous-owner reservation."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from shantytown import feed_check
from shantytown.answer import Answer
from shantytown.notify import DeferralAlerter
from shantytown.sd import SdTracker


def released(tmp_path, monkeypatch, priority):
    row = dict(id="test-resumed", title="Resumed work", priority=priority,
               status="deferred", assignee="worker", defer_until="2020-01-01T00:00:00Z",
               notes="resume_when: closed:test-blocker", labels=[], created_at="2026-01-01T00:00:00Z")
    updates = []

    def update(identifier, **fields):
        assert identifier == row["id"]
        updates.append(fields)
        row.update(fields)

    adapter = feed_check.TrackerAdapter.__new__(feed_check.TrackerAdapter)
    adapter.tracker = SimpleNamespace(update=update)
    adapter.show = lambda _: Answer.complete_read(dict(row), how="fixture")
    monkeypatch.setattr(feed_check, "backend_adapter", lambda *a: adapter)
    DeferralAlerter(tmp_path, None, None, read=lambda: [dict(row)],
                    show=lambda _: dict(row), is_closed=lambda _: True,
                    now=lambda: datetime(2026, 11, 14, tzinfo=timezone.utc),
                    push=lambda *a: pytest.fail("release must not dispatch")).sweep()
    assert len(updates) == 1
    assert row["status"] == "open" and not row["defer_until"]
    assert not row["assignee"], "resume silently reserved the previous owner's haul"
    return row


def test_resumed_p1_cannot_self_feed_ahead_of_ready_p0(tmp_path, monkeypatch):
    resumed = released(tmp_path, monkeypatch, 1)
    p0 = dict(id="test-milestone", title="P0 milestone child", priority=0,
              status="open", assignee="", created_at="2026-01-01T00:00:00Z")
    ready = SdTracker._tend_order([resumed, p0])
    assert feed_check.hauls(ready) == {}
    assert [i for i, _ in feed_check.dispatchable({"worker"}, ready)] == [p0["id"], resumed["id"]]


def test_resumed_p0_still_enters_ranked_pool(tmp_path, monkeypatch):
    resumed = released(tmp_path, monkeypatch, 0)
    p1 = dict(id="test-p1", title="Other work", priority=1, status="open", assignee="", created_at="2026-01-01T00:00:00Z")
    ready = SdTracker._tend_order([p1, resumed])
    assert [i for i, _ in feed_check.dispatchable({"worker"}, ready)] == [resumed["id"], p1["id"]]


def test_legacy_resume_clears_owner_in_same_write():
    adapter = feed_check.TrackerAdapter.__new__(feed_check.TrackerAdapter)
    adapter.tracker = None
    calls = []
    adapter._legacy = lambda *args: calls.append(args)
    adapter.undefer("test-resumed")
    assert calls == [("bd", "update", "test-resumed", "--status", "open",
                      "--defer", "", "--assignee", "", "--json")]
