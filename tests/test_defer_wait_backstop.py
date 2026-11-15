"""CI stays active; genuine appointments and other event gates retain pacing."""
from datetime import datetime, timedelta, timezone

import pytest

from shantytown.dispatch import DeferRefused, Dispatcher
from shantytown.files import FilesRegistry, FilesTracker
from shantytown.tmux import NullPanes
from test_deferral_owner_pacing import NOW, row, sweep, provenance


@pytest.fixture
def world(tmp_path):
    tracker = FilesTracker(tmp_path / "items")
    tracker.update("test-wait", title="work", status="open", assignee="worker")
    return Dispatcher(FilesRegistry(tmp_path / "crew"), tracker, NullPanes()), tracker


def future(hours):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat(timespec="seconds").replace("+00:00", "Z")


@pytest.mark.parametrize("reason", ["CI pending", "waiting for review", "merge wait", "install pending"])
def test_short_pipeline_date_refuses_before_any_write(world, reason):
    d, tracker = world
    before = tracker._path("test-wait").read_bytes()
    with pytest.raises(DeferRefused, match="resume_when.*24" if reason == "install pending" else "stay in_progress"):
        d.defer("test-wait", "external", reason, until=future(1))
    assert tracker._path("test-wait").read_bytes() == before


def test_real_scheduled_window_is_explicit_and_preserved(world):
    d, tracker = world
    d.defer("test-wait", "external", "review appointment at the scheduled window",
            until=future(1), window=True, gate_authority="worker")
    assert tracker.get("test-wait").status == "deferred"
    assert "defer_window: scheduled" in tracker.get("test-wait").notes


def test_event_requires_long_backstop_but_can_be_repeated_without_extension(world):
    d, tracker = world
    # A registered controller event is not a CI/review wait.
    reason = "resume_when: activation:test-wait"
    with pytest.raises(DeferRefused, match="24"):
        d.defer("test-wait", "external", reason)
    with pytest.raises(DeferRefused, match="24"):
        d.defer("test-wait", "external", reason, until=future(12))
    until = future(25)
    d.defer("test-wait", "external", reason, until=until, gate_authority="worker")
    assert d.defer("test-wait", "external", reason, until=until, gate_authority="worker").noop
    assert tracker.get("test-wait").defer_until == until


def test_timer_only_long_ci_wait_and_dry_run_cannot_bypass_event(world):
    d, tracker = world
    before = tracker._path("test-wait").read_bytes()
    for hours in (1, 7, 25):
        with pytest.raises(DeferRefused, match="stay in_progress"):
            d.defer("test-wait", "external", "CI pending", until=future(hours), dry_run=True)
    assert tracker._path("test-wait").read_bytes() == before


def test_unrelated_short_timer_is_not_misclassified_as_a_review(world):
    d, tracker = world
    d.defer("test-wait", "external", "waiting for a preview appointment", until=future(1))
    assert tracker.get("test-wait").status == "deferred"


@pytest.mark.parametrize("condition", ["installed:sd@0.6.7", "release:example/ci@v1.0"])
def test_marker_identifiers_are_not_misclassified_as_polling_prose(world, condition):
    d, tracker = world
    d.defer("test-wait", "external", "resume_when: " + condition)
    assert tracker.get("test-wait").status == "deferred"


def test_cli_window_flag_reaches_the_writer(tmp_path):
    from shantytown import cli
    tracker = FilesTracker(tmp_path / "items")
    tracker.update("test-wait", title="appointment", status="open", assignee="worker")
    assert cli.main(["--root", str(tmp_path), "work", "defer", "test-wait", "external",
                     "--reason", "scheduled review meeting", "--until", future(1), "--window"]) == 0
    assert "defer_window: scheduled" in tracker.get("test-wait").notes


def test_redeferral_archives_previous_setter_without_losing_history(world):
    from shantytown.deferral_pacing import owner_window
    import json
    d, tracker = world
    for hours in (1, 2):
        d.defer("test-wait", "external", f"CI meeting {hours}", until=future(hours),
                window=True, gate_authority="worker")
    item = json.loads(tracker._path("test-wait").read_text())
    assert item["notes"].count("\ndefer_provenance: ") == 1
    assert "historical defer provenance:" in item["notes"]
    assert "CI meeting 1" in item["notes"] and "CI meeting 2" in item["notes"]
    assert owner_window(item, datetime.now(timezone.utc), event_ready=True)


def test_live_owner_never_becomes_admin_merely_after_three_observations(tmp_path):
    item = row()
    for n in range(6):
        sent, admin, result = sweep(tmp_path, [item])
        assert not admin and not result
        assert bool(sent) == (n == 0)
    assert item["status"] == "deferred"


def test_long_owner_timer_returns_to_owner_and_down_owner_still_escalates(tmp_path):
    item = row()
    item["notes"] = provenance("worker", (NOW - timedelta(days=2)).isoformat(), item["defer_until"])
    sent, admin, _ = sweep(tmp_path, [item])
    assert sent and not admin
    sent, admin, _ = sweep(tmp_path, [item], live=False)
    assert not sent and admin


def test_met_event_prompts_owner_before_backstop_without_releasing_gate(tmp_path, monkeypatch):
    from shantytown import deferrals
    item = row(defer_until=(NOW + timedelta(days=1)).isoformat())
    item["notes"] = provenance("worker", (NOW - timedelta(hours=1)).isoformat(), item["defer_until"])
    finding = deferrals.Finding(bead=item["id"], priority=0,
                               condition=deferrals.Condition("event", "test-binding"), met=True)
    monkeypatch.setattr(deferrals, "evaluate", lambda *args, **kwargs: [finding])
    monkeypatch.setattr(deferrals, "can_release", lambda *args: False)
    sent, admin, _ = sweep(tmp_path, [item])
    assert sent and not admin
    assert item["status"] == "deferred"


def test_unmet_event_at_owner_backstop_prompts_owner_not_release(tmp_path, monkeypatch):
    from shantytown import deferrals
    item = row()
    finding = deferrals.Finding(bead=item["id"], priority=0, lapsed_at=NOW - timedelta(minutes=1),
                               condition=deferrals.Condition("event", "test-binding"), met=False)
    monkeypatch.setattr(deferrals, "evaluate", lambda *args, **kwargs: [finding])
    sent, admin, _ = sweep(tmp_path, [item])
    assert sent and not admin
    assert item["status"] == "deferred"
