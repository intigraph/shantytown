import json
from types import SimpleNamespace

import pytest

from shantytown import cli
from shantytown.sd import SdTracker
from shantytown.task_intake import deadline


@pytest.mark.parametrize("value, expected", [
    ("2026-11-09", "2026-11-09T00:00:00Z"),
    ("2026-11-09T08:30:00Z", "2026-11-09T08:30:00Z"),
    ("2026-11-09T03:30:00-05:00", "2026-11-09T08:30:00Z"),
])
def test_explicit_deadlines_are_normalized_without_a_default(value, expected):
    assert deadline(value, "1") == expected
    assert deadline(None, "0") is None


@pytest.mark.parametrize("value, policy", [
    (None, "1"), (None, "unknown"), ("", "0"), ("tomorrow", "1"),
    ("2026-11-09T08:30:00", "1"), ("2026-02-30", "1"),
])
def test_bad_intake_refuses_before_tracker_capacity_or_advisory(tmp_path, monkeypatch, value, policy):
    monkeypatch.setenv("SHANTY_TASK_DUE_REQUIRED", policy)
    def forbidden(*args, **kwargs):
        raise AssertionError("no tracker read or creation permitted")
    monkeypatch.setattr(cli, "_tracker", forbidden)
    args = ["--root", str(tmp_path), "task", "new work"]
    if value is not None:
        args += ["--due", value]
    assert cli.main(args) == cli.REFUSED
    assert not (tmp_path / "items").exists()


def test_required_deadline_is_persisted_in_files_and_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SHANTY_TASK_DUE_REQUIRED", "1")
    args = ["--root", str(tmp_path), "task", "new work", "--due", "2026-11-09"]
    assert cli.main(args + ["--dry-run"]) == cli.OK
    assert "due=2026-11-09T00:00:00Z" in capsys.readouterr().out
    assert not (tmp_path / "items").exists()
    assert cli.main(args) == cli.OK
    rows = [json.loads(p.read_text()) for p in (tmp_path / "items").glob("*.json")]
    assert len(rows) == 1 and rows[0]["due_at"] == "2026-11-09T00:00:00Z"


def test_selected_seeds_adapter_uses_native_due_flag_without_followup_mutation(monkeypatch):
    tracker = object.__new__(SdTracker)
    calls = []
    def native(*args):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout='{"id":"test-1"}', stderr="")
    monkeypatch.setattr(tracker, "_bd", native)
    item = tracker.create("dated work", due_at="2026-11-09T00:00:00Z")
    assert item.due_at == "2026-11-09T00:00:00Z"
    assert len(calls) == 1 and "--due=2026-11-09T00:00:00Z" in calls[0]
    assert not any("due-at" in arg for arg in calls[0])
