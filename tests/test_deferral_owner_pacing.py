"""Owner-only reminders never release an item or hide a real judgement gate."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
from shantytown.deferral_pacing import OwnerPacing, owner_window, provenance
from shantytown.notify import DeferralAlerter
from shantytown.stopped import FilesStops

NOW = datetime(2026, 10, 24, 5, 30, tzinfo=timezone.utc)


def row(identifier="test-ci", **changes):
    end = (NOW - timedelta(minutes=1)).isoformat()
    value = {"id": identifier, "status": "deferred", "assignee": "worker",
             "title": "CI wait", "priority": 0, "labels": ["blocked:external"],
             "updated_at": (NOW - timedelta(minutes=15)).isoformat(),
             "defer_until": end,
             "notes": "CI pending\nresume_when: date:" + end + "\n" + provenance(
                 "worker", (NOW - timedelta(minutes=16)).isoformat(), end)}
    return value | changes


def sweep(tmp_path, rows, *, live=True, stopped=False, send_error=False, log=None,
          admin_available=True, now=None):
    sent, admin = [], []
    card = SimpleNamespace(name="worker", retired=False, pane="worker-pane")
    reg = SimpleNamespace(get=lambda name: card)
    def send(pane, text):
        if send_error:
            raise OSError("delivery failed")
        sent.append((pane, text))
    panes = SimpleNamespace(exists=lambda pane: live, send=send,
                            cmdline=lambda pane: "claude --settings /tmp/private/settings.json")
    if stopped:
        FilesStops(tmp_path / "stopped").record("worker", NOW.timestamp())
    def push(*args):
        if admin_available:
            admin.append(args[-1])
            return "admin"
        return None
    alerter = DeferralAlerter(tmp_path, reg, panes, read=lambda: rows,
                             now=lambda: now or NOW, push=push, log=log)
    result = alerter.sweep()
    return sent, admin, result


def test_admin_digest_log_counts_only_successful_delivery_once(tmp_path):
    logs = []
    item = row()
    assert sweep(tmp_path, [item], live=False, log=logs.append)[1]
    assert not sweep(tmp_path, [item], live=False, log=logs.append)[1]
    delivered = [line for line in logs if "ADMIN-DIGEST delivered" in line]
    assert len(delivered) == 1
    assert "count=1 digest=" in delivered[0]
    assert len(delivered[0].split("digest=", 1)[1]) == 64


def test_owner_and_quiet_reports_are_not_admin_digest_deliveries(tmp_path):
    logs = []
    assert sweep(tmp_path / "owner", [row()], log=logs.append)[0]
    assert not sweep(tmp_path / "quiet", [row(priority=2)], live=False, log=logs.append)[1]
    assert any("deferral log:" in line for line in logs)
    assert not any("ADMIN-DIGEST" in line for line in logs)


def test_failed_admin_delivery_does_not_count_or_consume_retry(tmp_path):
    logs = []
    item = row()
    assert not sweep(tmp_path, [item], live=False, admin_available=False, log=logs.append)[1]
    assert not any("ADMIN-DIGEST" in line for line in logs)
    assert sweep(tmp_path, [item], live=False, log=logs.append)[1]
    assert sum("ADMIN-DIGEST delivered" in line for line in logs) == 1


def test_nine_owner_waits_stay_with_live_owner_after_three_passes(tmp_path):
    # Contract replay, not a claim these synthetic rows are historical packets.
    rows = [row(f"test-{n}") for n in range(9)]
    sent, admin, result = sweep(tmp_path, rows)
    assert len(sent) == 9 and admin == result == []
    assert all("OWNER-PACING" in text for _, text in sent)
    assert sweep(tmp_path, rows) == ([], [], [])
    sent, admin, result = sweep(tmp_path, rows)
    assert not sent and not admin and not result
    assert sweep(tmp_path, rows) == ([], [], [])


@pytest.mark.parametrize("change", [
    {"title": "ASK Stiwi: decide"}, {"labels": ["desk"]},
    {"assignee": "other"}, {"notes": "CI wait"},
    {"updated_at": None}, {"updated_at": (NOW + timedelta(seconds=1)).isoformat()},
    {"defer_until": (NOW - timedelta(minutes=2)).isoformat()},
])
def test_ineligible_or_unknown_evidence_retains_admin_ruling(tmp_path, change):
    sent, admin, result = sweep(tmp_path, [row(**change)])
    assert sent == [] and admin and result == ["test-ci"]


@pytest.mark.parametrize("options", [{"live": False}, {"stopped": True}, {"send_error": True}])
def test_down_stopped_or_failed_delivery_escalates(tmp_path, options):
    sent, admin, result = sweep(tmp_path, [row()], **options)
    assert sent == [] and admin and result == ["test-ci"]


def test_exact_sixty_minute_boundary_and_long_control():
    item = row()
    end = item["defer_until"]
    for minutes, expected in [(60, True), (61, True), (24 * 60, True), (0, False)]:
        start = NOW - timedelta(minutes=minutes + 1)
        item["notes"] = provenance("worker", start.isoformat(), end)
        assert owner_window(item, NOW) is expected


def test_item_update_resets_count_and_re_nudges(tmp_path):
    item = row()
    assert sweep(tmp_path, [item])[0]
    assert not sweep(tmp_path, [item])[0]
    item["updated_at"] = (NOW - timedelta(seconds=1)).isoformat()
    sent, admin, _ = sweep(tmp_path, [item])
    assert sent and not admin


def test_unreadable_stop_record_cannot_earn_owner_only_route(tmp_path):
    stop = tmp_path / "stopped" / "worker.json"
    stop.parent.mkdir()
    stop.write_text("not json")
    sent, admin, result = sweep(tmp_path, [row()])
    assert not sent and admin and result == ["test-ci"]


def test_met_event_with_prose_gate_gets_owner_recheck_not_automatic_release(tmp_path, monkeypatch):
    from shantytown import deferrals
    item = row()
    finding = deferrals.Finding(bead=item["id"], priority=0,
                               lapsed_at=NOW - timedelta(minutes=1),
                               condition=deferrals.Condition("event", "test-binding"), met=True)
    monkeypatch.setattr(deferrals, "evaluate", lambda *args, **kwargs: [finding])
    monkeypatch.setattr(deferrals, "can_release", lambda *args: False)
    sent, admin, result = sweep(tmp_path, [item])
    assert sent and not admin and result == []
    assert item["status"] == "deferred"


def test_writer_retains_actor_time_and_bound_deadline_without_breaking_noop(tmp_path):
    from shantytown.dispatch import Dispatcher
    from shantytown.files import FilesRegistry, FilesTracker
    from shantytown.tmux import NullPanes
    tracker = FilesTracker(tmp_path / "items")
    tracker.update("test-ci", title="CI wait", status="open", assignee="worker")
    dispatcher = Dispatcher(FilesRegistry(tmp_path / "crew"), tracker, NullPanes())
    until = (datetime.now(timezone.utc) + timedelta(minutes=15)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    result = dispatcher.defer("test-ci", "external", "CI wait", until=until,
                              gate_authority="worker", window=True)
    notes = tracker.get("test-ci").notes
    assert '"actor": "worker"' in notes and '"until":' in notes
    assert dispatcher.defer("test-ci", "external", "CI wait", until=until,
                            gate_authority="worker", window=True).noop
    assert tracker.get("test-ci").notes == notes
    assert result.reason in notes


@pytest.mark.parametrize("extra", ["duplicate", "other-setter", "malformed", "indented", "missing-space"])
@pytest.mark.parametrize("position", ["before", "after"])
def test_ambiguous_envelopes_keep_admin_route_end_to_end(tmp_path, extra, position):
    item = row()
    valid = item["notes"].splitlines()[-1]
    candidate = {
        "duplicate": valid,
        "other-setter": valid.replace('"worker"', '"administrator"'),
        "malformed": 'defer_provenance: {broken',
        "indented": '  ' + valid,
        "missing-space": valid.replace('defer_provenance: ', 'defer_provenance:'),
    }[extra]
    item["notes"] = (candidate + "\n" + item["notes"] if position == "before"
                     else item["notes"] + "\n" + candidate)
    assert not owner_window(item, NOW)
    sent, admin, result = sweep(tmp_path, [item])
    assert sent == [] and admin and result == ["test-ci"]
    assert item["status"] == "deferred"


def test_single_canonical_envelope_keeps_owner_route_end_to_end(tmp_path):
    item = row()
    assert owner_window(item, NOW)
    sent, admin, result = sweep(tmp_path, [item])
    assert len(sent) == 1 and "OWNER-PACING" in sent[0][1]
    assert admin == result == [] and item["status"] == "deferred"


def aged_row(hours, **changes):
    end = NOW - timedelta(hours=hours)
    return row(defer_until=end.isoformat(),
               updated_at=(end - timedelta(minutes=1)).isoformat(),
               notes="CI pending\nresume_when: date:" + end.isoformat() + "\n"
               + provenance("worker", (end - timedelta(days=1)).isoformat(),
                            end.isoformat())) | changes


@pytest.mark.parametrize("hours", [72, 73])
def test_unchanged_lapsed_owner_timer_reaches_admin_once_at_ceiling(tmp_path, hours):
    item = aged_row(hours)
    sent, admin, result = sweep(tmp_path, [item])
    assert not sent and len(admin) == 1 and result == [item["id"]]
    assert sweep(tmp_path, [item]) == ([], [], [])
    assert item["status"] == "deferred"  # escalation never releases the gate


def test_71_hour_lapse_stays_with_owner_regardless_of_sweep_count(tmp_path):
    item = aged_row(71)
    assert sweep(tmp_path, [item])[0]
    for _ in range(4):
        assert sweep(tmp_path, [item]) == ([], [], [])


def test_recent_touch_resets_elapsed_ceiling_for_old_deadline(tmp_path):
    item = aged_row(73, updated_at=(NOW - timedelta(hours=71)).isoformat())
    sent, admin, result = sweep(tmp_path, [item])
    assert sent and not admin and not result


def test_already_nudged_owner_escalates_when_elapsed_ceiling_crosses(tmp_path):
    item = aged_row(71)
    assert sweep(tmp_path, [item])[0]
    later = NOW + timedelta(hours=2)
    sent, admin, result = sweep(tmp_path, [item], now=later)
    assert not sent and len(admin) == 1 and result == [item["id"]]
    assert sweep(tmp_path, [item], now=later) == ([], [], [])
