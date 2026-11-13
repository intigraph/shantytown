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
