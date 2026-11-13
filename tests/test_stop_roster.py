"""Stop-event entry points must prepare one roster before reading any plate."""
import json

import pytest

from shantytown import stop_event
from shantytown.answer import Answer
from shantytown.events import FilesEvents


class RosterTracker:
    def __init__(self, *, unavailable=False):
        self.prepared = []
        self.reads = []
        self.unavailable = unavailable

    def prepare_roster(self, owners):
        self.prepared.append(tuple(owners))

    def plate_rows(self, owner):
        assert len(self.prepared) == 1, "per-agent fallback reached"
        assert owner in self.prepared[0]
        self.reads.append(owner)
        if self.unavailable:
            return Answer.capped([], how="roster", caveat="HTTP 408")
        rows = ([dict(id="work-1", title="Current work", status="in_progress",
                      priority=1, assignee=owner)] if owner == "worker" else [])
        return Answer.complete_read(rows, how="roster")


def setup(root, monkeypatch, me, tracker):
    crew = root / "crew"
    crew.mkdir()
    for name, role in (("admin", "administrator"), ("lead", "lead"),
                       ("worker", "worker")):
        (crew / f"{name}.json").write_text(json.dumps(
            dict(role=role, pane=f"p-{name}", reports_to="admin")))
    (root / "shantytown.toml").write_text('[env]\nSHANTY_BACKEND="seeds"\n')
    monkeypatch.setenv("SHANTY_AGENT", me)
    monkeypatch.setattr(stop_event, "_stop_identity", lambda *a: me)
    monkeypatch.setattr(stop_event, "Tmux", lambda **kw: type(
        "Panes", (), {"exists": lambda *a: False})())
    monkeypatch.setattr(stop_event, "_liveness", lambda *a, **kw: "?")
    monkeypatch.setattr("shantytown.job_launch.local_job", lambda: None)
    monkeypatch.setattr("shantytown.sd.br_like_tracker", lambda *a, **kw: tracker)


@pytest.mark.parametrize("me,expected", [
    ("admin", ("admin", "lead", "worker")),
    ("lead", ("lead", "worker")),
])
def test_real_drain_entry_shares_roster_for_display_and_workflow(
        tmp_path, monkeypatch, capsys, me, expected):
    tracker = RosterTracker()
    setup(tmp_path, monkeypatch, me, tracker)
    FilesEvents(tmp_path / "events").persist(to=me, frm="worker", reason="stopped", rose=False)
    assert stop_event.main(["drain", "--root", str(tmp_path)]) == 0
    reason = json.loads(capsys.readouterr().out)["reason"]
    assert tracker.prepared == [expected]
    assert tracker.reads.count("worker") == 1  # display + workflow share snapshot
    assert "work-1" in reason
    assert "PLATE UNKNOWN" not in reason


def test_roster_failure_stays_unknown_without_per_agent_retry(tmp_path, monkeypatch, capsys):
    tracker = RosterTracker(unavailable=True)
    setup(tmp_path, monkeypatch, "admin", tracker)
    FilesEvents(tmp_path / "events").persist(to="admin", frm="worker", reason="stopped", rose=False)
    assert stop_event.main(["drain", "--root", str(tmp_path)]) == 0
    reason = json.loads(capsys.readouterr().out)["reason"]
    assert tracker.prepared == [("admin", "lead", "worker")]
    assert tracker.reads.count("worker") == 1
    assert "PLATE UNKNOWN" in reason
    assert "assign work" not in reason


def test_send_time_item_uses_single_owner_roster(tmp_path, monkeypatch):
    tracker = RosterTracker()
    setup(tmp_path, monkeypatch, "worker", tracker)
    assert stop_event._plate_of(tmp_path, "worker") == ("work-1", "in_progress", [])
    assert tracker.prepared == [("worker",)]


def test_incomplete_admin_roster_never_falls_back(tmp_path, monkeypatch, capsys):
    tracker = RosterTracker()
    setup(tmp_path, monkeypatch, "admin", tracker)
    monkeypatch.setattr(stop_event.FilesRegistry, "all", lambda self: Answer.capped(
        [], how="registry", caveat="partial crew"))
    FilesEvents(tmp_path / "events").persist(to="admin", frm="worker", reason="stopped", rose=False)
    assert stop_event.main(["drain", "--root", str(tmp_path)]) == 0
    assert tracker.prepared == []
    assert tracker.reads == []
    assert "unreadable" in json.loads(capsys.readouterr().out)["reason"].lower()


def real_projection(tmp_path, monkeypatch, me):
    """Keep the real SdTracker roster/fallback decision, isolate only its wire."""
    from shantytown import seeds_plate
    from shantytown.sd import SdTracker, StoreProof
    tracker = SdTracker(quipu="https://example.test", prefix="test")
    setup(tmp_path, monkeypatch, me, tracker)
    monkeypatch.setattr(tracker, "_use_remote_projection", lambda: True)
    monkeypatch.setattr(tracker, "prove_store", lambda: StoreProof(
        "--quipu", None, "https://example.test", "test", "urn:test:graph"))
    calls = []

    def owner_rows(proof, agent, **kwargs):
        calls.append((agent, kwargs.get("plate_owners")))
        return Answer.complete_read([], how="isolated projection wire")

    monkeypatch.setattr(seeds_plate, "owner_rows", owner_rows)
    monkeypatch.setattr(seeds_plate, "unblocked_ids", lambda *a, **kw: set())
    return calls


def test_late_sender_is_unknown_without_real_tracker_per_agent_fallback(
        tmp_path, monkeypatch, capsys):
    calls = real_projection(tmp_path, monkeypatch, "lead")
    FilesEvents(tmp_path / "events").persist(to="lead", frm="worker", reason="stopped", rose=False)
    original = FilesEvents.pending
    scans = 0

    def pending(self, who):
        nonlocal scans
        scans += 1
        return [] if scans == 1 else original(self, who)

    monkeypatch.setattr(FilesEvents, "pending", pending)
    assert stop_event.main(["drain", "--root", str(tmp_path)]) == 0
    reason = json.loads(capsys.readouterr().out)["reason"]
    assert not any(agent is not None for agent, _owners in calls), calls
    assert "unreadable" in reason.lower()


def test_registry_expansion_is_unknown_without_real_tracker_fallback(
        tmp_path, monkeypatch, capsys):
    calls = real_projection(tmp_path, monkeypatch, "admin")
    FilesEvents(tmp_path / "events").persist(to="admin", frm="worker", reason="stopped", rose=False)
    original = stop_event.FilesRegistry.all
    scans = 0

    def growing(self):
        nonlocal scans
        scans += 1
        observed = original(self)
        if scans == 1:
            (tmp_path / "crew" / "newworker.json").write_text(json.dumps(
                dict(role="worker", pane="p-newworker", reports_to="admin")))
        return observed

    monkeypatch.setattr(stop_event.FilesRegistry, "all", growing)
    assert stop_event.main(["drain", "--root", str(tmp_path)]) == 0
    reason = json.loads(capsys.readouterr().out)["reason"]
    assert any(agent is None for agent, _owners in calls), calls
    assert not any(agent is not None for agent, _owners in calls), calls
    assert "PLATE UNKNOWN" in reason and "newworker" in reason
