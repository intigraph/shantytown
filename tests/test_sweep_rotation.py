import json

from shantytown.sweep_rotation import SweepRotation


def test_slow_prefix_cannot_starve_later_sweeps_across_passes(tmp_path):
    counts = {name: 0 for name in ("slow", "deferral-sweep", "tail")}
    for _ in range(6):
        rotation = SweepRotation(tmp_path)
        elapsed = 0
        for name in counts:
            if rotation.admission(name, within_budget=elapsed <= 120) is None:
                counts[name] += 1
                elapsed += 130 if name == "slow" else 1
        rotation.finish()
    assert counts == {"slow": 3, "deferral-sweep": 3, "tail": 3}


def test_budget_cursor_advances_through_multiple_slow_sweeps(tmp_path):
    runs = []
    for _ in range(4):
        rotation = SweepRotation(tmp_path)
        elapsed = 0
        for label in ("a", "b", "c"):
            if rotation.admission(label, within_budget=elapsed <= 120) is None:
                runs.append(label)
                elapsed += 121
        rotation.finish()
    assert runs == ["a", "b", "c", "a"]


def test_skips_are_unknown_and_do_not_invoke_condition_reads(tmp_path):
    path = tmp_path / "notify" / "tend-sweep-rotation.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"version": 1, "next": "late"}))
    rotation = SweepRotation(tmp_path)
    assert rotation.admission("early", within_budget=True) == "rotation"
    assert rotation.admission("late", within_budget=True) is None
    assert rotation.admission("later", within_budget=False) == "budget"
    assert rotation.started == ["late"]
    assert rotation.rotated == ["early"]
    rotation.finish()
    assert json.loads(path.read_text())["next"] == "later"


def test_absent_optional_cursor_recovers_on_next_pass(tmp_path):
    rotation = SweepRotation(tmp_path)
    rotation.admission("optional", within_budget=False)
    rotation.finish()
    rotation = SweepRotation(tmp_path)
    assert rotation.admission("always", within_budget=True) == "rotation"
    rotation.finish()
    assert SweepRotation(tmp_path).admission("always", within_budget=True) is None


def test_dynamic_cycle_cursor_reenters_through_request_reader(tmp_path):
    rotation = SweepRotation(tmp_path)
    rotation.admission("cycle:worker", within_budget=False)
    rotation.finish()
    resumed = SweepRotation(tmp_path)
    assert resumed.admission("cycle-requests", within_budget=True) is None


def test_dry_run_does_not_advance_persistent_schedule(tmp_path):
    rotation = SweepRotation(tmp_path)
    rotation.admission("late", within_budget=False)
    rotation.finish()
    before = rotation.path.read_bytes()
    preview = SweepRotation(tmp_path, dry_run=True)
    preview.admission("late", within_budget=True)
    preview.finish()
    assert rotation.path.read_bytes() == before


def test_bad_ledger_and_write_failure_do_not_stop_supervision(tmp_path, monkeypatch):
    rotation = SweepRotation(tmp_path)
    rotation.path.parent.mkdir()
    rotation.path.write_text("not json")
    messages = []
    rotation = SweepRotation(tmp_path, log=messages.append)
    assert rotation.admission("first", within_budget=True) is None
    def fail(*args):
        raise OSError("disk full")
    monkeypatch.setattr("shantytown.sweep_rotation.write_json_atomic", fail)
    rotation.finish()
    assert any("state UNKNOWN" in line for line in messages)
    assert any("persistence UNKNOWN" in line for line in messages)


def test_overdue_service_preserves_the_other_sweeps_cursor(tmp_path):
    path = tmp_path / "notify" / "tend-sweep-rotation.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"version": 1, "next": "late"}))
    rotation = SweepRotation(tmp_path)
    assert rotation.admission("overdue-sweep", within_budget=True) is None
    assert rotation.admission("early", within_budget=True) == "rotation"
    assert rotation.admission("late", within_budget=True) is None
    assert rotation.admission("tail", within_budget=False) == "budget"
    rotation.finish()
    assert json.loads(path.read_text())["next"] == "tail"


def test_overdue_does_not_bypass_the_time_budget(tmp_path):
    rotation = SweepRotation(tmp_path)
    assert rotation.admission("overdue-sweep", within_budget=False) == "budget"
    assert rotation.started == []
