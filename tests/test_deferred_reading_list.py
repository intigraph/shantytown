"""The old-work band reuses tend's snapshot and never clears its gates."""
import copy
import json
from datetime import datetime, timedelta, timezone

from shantytown import deferrals
from shantytown.notify import DeferralAlerter

NOW = datetime(2026, 10, 13, tzinfo=timezone.utc)


def row(name="old", age=40, **extra):
    return {"id": name, "title": "reading fixture", "priority": 3,
            "assignee": "fixture", "status": "deferred", "notes": "",
            "updated_at": (NOW - timedelta(days=age)).isoformat(),
            "defer_until": (NOW + timedelta(days=10)).isoformat(), **extra}


def test_reading_band_includes_future_gates_both_representations_and_exact_boundary():
    rows = [row("forty"), row("thirty", 30, status="open"), row("young", 29),
            row("closed", status="closed"), row("ordinary", status="open", defer_until=None)]
    before = copy.deepcopy(rows)
    result = deferrals.reading_list(rows, NOW)
    assert result["confidence"] == "CONFIRMED"
    assert [(item["id"], item["age_days"]) for item in result["untouched_30d"]] == [
        ("forty", 40), ("thirty", 30)]
    assert result["age_unknown"] == []
    assert rows == before
    assert deferrals.evaluate(rows[:2], NOW) == [], "age cannot change mechanical gate"


def test_unknown_touch_age_is_preserved_beside_positive_old_control():
    rows = [row("known"), row("missing", updated_at=None),
            row("malformed", updated_at="yesterday"),
            row("future", updated_at=(NOW + timedelta(days=1)).isoformat())]
    report = deferrals.reading_list(rows, NOW)
    assert report["confidence"] == "UNKNOWN"
    assert [item["id"] for item in report["untouched_30d"]] == ["known"]
    assert {item["id"] for item in report["age_unknown"]} == {
        "missing", "malformed", "future"}
    blind = deferrals.reading_list([], NOW, snapshot_ok=False)
    assert blind["confidence"] == "UNKNOWN" and blind["error"]


def test_snapshot_is_consumed_once_without_show_release_or_pane_wake(tmp_path):
    calls = []
    rows = [row()]
    def read():
        calls.append("read")
        return rows
    def forbidden(*args):
        raise AssertionError("age reporting must not fetch, release or wake")
    alerter = DeferralAlerter(tmp_path, None, None, read=read, now=NOW,
                             show=forbidden, release=forbidden, push=forbidden)
    assert alerter.sweep() == []
    report_path = tmp_path / "notify/deferred-reading-list.json"
    report = json.loads(report_path.read_text())
    assert calls == ["read"]
    assert report["confidence"] == "CONFIRMED"
    assert [item["id"] for item in report["untouched_30d"]] == ["old"]
    rows[0]["updated_at"] = NOW.isoformat()
    assert alerter.sweep() == []
    assert json.loads(report_path.read_text())["untouched_30d"] == []
    assert calls == ["read", "read"]


def test_failed_snapshot_replaces_previous_report_with_unknown(tmp_path):
    alerter = DeferralAlerter(tmp_path, None, None, read=lambda: [row()],
                             now=NOW, push=lambda *args: None)
    alerter.sweep()
    def unreadable():
        raise OSError("fixture read failure")
    alerter._read = unreadable
    alerter.sweep()
    report = json.loads((tmp_path / "notify/deferred-reading-list.json").read_text())
    assert report["confidence"] == "UNKNOWN"
    assert report["error"] == "deferred snapshot unreadable"
    assert report["untouched_30d"] == []


def test_failed_report_publication_cannot_log_confirmed_completion(tmp_path, monkeypatch):
    from shantytown import files
    original = files.write_json_atomic
    def write(path, data):
        if path.name == "deferred-reading-list.json":
            raise OSError("fixture publication failure")
        return original(path, data)
    monkeypatch.setattr(files, "write_json_atomic", write)
    logs = []
    alerter = DeferralAlerter(tmp_path, None, None, read=lambda: [row()],
                             now=NOW, log=logs.append, push=lambda *args: None)
    assert alerter.sweep() == []
    assert any("reading list: UNKNOWN publication" in line for line in logs)
    assert not any("CONFIRMED" in line for line in logs)
