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


def test_duplicate_override_forwards_repeated_ids_and_reason_in_one_command(monkeypatch):
    tracker = object.__new__(SdTracker)
    calls = []
    def native(*args):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout='{"id":"test-2"}', stderr="")
    monkeypatch.setattr(tracker, "_bd", native)
    tracker.create("same title", new_despite=["test-1", "test-3"], because="separate deployment",
                   description="more detail")
    assert len(calls) == 1
    assert "--new-despite=test-1" in calls[0] and "--new-despite=test-3" in calls[0]
    assert "--because=separate deployment" in calls[0]
    assert "--description=more detail" in calls[0]


def test_duplicate_refusal_retains_candidate_and_is_definite(monkeypatch, tmp_path, capsys):
    from shantytown.sd import CreateRefused
    tracker = object.__new__(SdTracker)
    monkeypatch.setattr(tracker, "_bd", lambda *args: SimpleNamespace(
        returncode=5, stdout="", stderr="near-duplicate: comment on test-1 instead"))
    with pytest.raises(CreateRefused, match="comment on test-1"):
        tracker.create("same title")
    monkeypatch.setattr(cli, "_tracker", lambda a: tracker)
    assert cli.main(["--root", str(tmp_path), "task", "same title"]) == cli.REFUSED
    assert "comment on test-1" in capsys.readouterr().err


@pytest.mark.parametrize("flags", [["--new-despite", "test-1"], ["--because", "why"],
                                   ["--new-despite", "test-1", "--because", " "]])
def test_partial_override_refuses_before_tracker(monkeypatch, tmp_path, flags):
    monkeypatch.setattr(cli, "_tracker", lambda a: pytest.fail("must not read the tracker"))
    assert cli.main(["--root", str(tmp_path), "task", "same title", *flags]) == cli.REFUSED
