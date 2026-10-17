"""Pending CI custody must not turn into repeated coordinator dispatch prompts."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from shantytown import feed_check, seeds_plate, stop_policy
from shantytown.answer import Answer, PartialAnswer
from shantytown import busy_wait

def waiting_on_event(row, now=None):
    return bool(busy_wait.from_rows([row], ["worker"], now=now))
from shantytown.sd import SdTracker

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def waiting(**overrides):
    row = dict(id="wait", title="wait for CI", status="in_progress",
               assignee="worker", labels=["blocked:external"], priority=2,
               defer_until=(NOW + timedelta(minutes=15)).isoformat())
    row.update(overrides)
    return row


@pytest.mark.parametrize("seconds,expected", [(-1, False), (0, False), (1, True),
                                               (86400, True), (86401, False)])
def test_review_boundary(seconds, expected):
    row = waiting(defer_until=(NOW + timedelta(seconds=seconds)).isoformat())
    assert waiting_on_event(row, NOW) is expected
    assert row["status"] == "in_progress"  # Expiry never opens or resumes work.


@pytest.mark.parametrize("stamp", [None, "", "tomorrow", "2026-01-01", "2026-01-01T01:00:00",
                                   "2026-01-01T01:00:00+01:00", "2026-99-01T01:00:00Z"])
def test_unreadable_gate_is_unknown_not_free(stamp):
    with pytest.raises(ValueError):
        waiting_on_event(waiting(defer_until=stamp), NOW)


@pytest.mark.parametrize("overrides", [{"status": "closed"}, {"status": "tombstone"}])
def test_resolved_or_different_custody_does_not_reserve(overrides):
    assert not waiting_on_event(waiting(**overrides), NOW)


def test_repeated_turns_waiting_silent_idle_still_blocks(monkeypatch, tmp_path):
    from test_busy_wait import world, verdict, row, NOW as clock
    values = [row(labels=["blocked:external"],
                  defer_until=(clock + timedelta(hours=2)).isoformat())]
    reg, panes, program = world(tmp_path, monkeypatch, values)
    assert sum(verdict(tmp_path, reg, panes, program).block for _ in range(10)) == 0
    for path in (tmp_path / "items").glob("*.json"):
        path.unlink()
    assert sum(verdict(tmp_path, reg, panes, program).block for _ in range(10)) == 10
    monkeypatch.setattr(busy_wait, "rows", lambda *a: Answer.capped([], how="fixture", caveat="partial").exact())
    assert feed_check.free_feedable_workers(reg, panes, program, tmp_path) == []


@pytest.mark.parametrize("row", [{"issue_type": "epic"}, {"labels": ["parked:by-design"]},
                                 {"labels": ["manual"]}, {"labels": ["needs-stiwi"]},
                                 {"assignee": "other"}])
def test_undispatchable_metadata_does_not_offer_work(row):
    assert feed_check.dispatchable({"worker"}, [dict(id="x", title="ordinary words", **row)]) == []


def test_titles_never_define_epic_or_manual_work():
    assert feed_check.dispatchable({"worker"}, [dict(id="x", title="manual epic implementation")]) == [
        ("x", "manual epic implementation")]

