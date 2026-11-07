"""Earlier feedback and repetition must reach administrators during a tool turn."""
import json

from shantytown import context_hint as ch
from test_context_hint import world, turn


def test_early_admin_nudge(tmp_path, capsys):
    card, payload = world(tmp_path, "administrator")
    turn(payload["transcript_path"], 550)
    assert ch.emit(tmp_path, card, payload)
    assert "CONTEXT NUDGE" in json.loads(capsys.readouterr().out)["reason"]
    assert ch._load(ch._path(tmp_path, card))["ceiling"] is None


def test_repeated_handoff_not_starved_by_busy_observations(tmp_path, monkeypatch, capsys):
    card, payload = world(tmp_path, "administrator")
    clock = [1000]
    monkeypatch.setattr(ch.time, "time", lambda: clock[0])
    assert ch.emit(tmp_path, card, payload)
    capsys.readouterr()
    for at in (1030, 1060, 1090):
        clock[0] = at
        assert not ch.emit(tmp_path, card, payload)
    clock[0] = 1120
    assert ch.emit(tmp_path, card, payload)
    assert "CONTEXT HINT" in json.loads(capsys.readouterr().out)["reason"]


def test_capture_entry_delivers_bounded_tool_context(tmp_path, monkeypatch, capsys):
    import io
    from shantytown import stats
    card, payload = world(tmp_path, "administrator")
    (tmp_path / "crew").mkdir()
    (tmp_path / "crew/reader.json").write_text(json.dumps({"role": card.role}))
    payload["hook_event_name"] = "PostToolUse"
    turn(payload["transcript_path"], 550)
    monkeypatch.setenv("SHANTY_AGENT", "reader")
    clock = [1000]
    monkeypatch.setattr(ch.time, "time", lambda: clock[0])
    monkeypatch.setattr(ch, "_decide", lambda *a: (_ for _ in ()).throw(AssertionError("tool feedback must not call Jev")))
    # Exercise the installed command entry and real capture, not only the emitter.
    def capture_once():
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
        assert stats.main(["capture", "--root", str(tmp_path)]) == 0
        return capsys.readouterr().out
    output = json.loads(capture_once())
    assert set(output) == {"hookSpecificOutput"}
    assert output["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    assert "CONTEXT NUDGE" in output["hookSpecificOutput"]["additionalContext"]
    for at in (1030, 1060, 1090):
        clock[0] = at
        assert capture_once() == ""
    clock[0] = 1120
    assert "CONTEXT NUDGE" in capture_once()
    assert not (tmp_path / "notify/cycle-requests.json").exists()
    assert not (tmp_path / "session_budget").exists()


def test_tool_hint_does_not_suppress_stop_decision_or_extend_exception(tmp_path, monkeypatch, capsys):
    card, payload = world(tmp_path, "administrator")
    (tmp_path / "crew").mkdir()
    (tmp_path / "crew/reader.json").write_text('{"role":"administrator"}')
    payload["hook_event_name"] = "PostToolUse"
    clock = [1000]
    monkeypatch.setattr(ch.time, "time", lambda: clock[0])
    decisions = []
    def decide(*args):
        decisions.append(True)
        return dict(decision="continue", reason="finish current safe operation")
    monkeypatch.setattr(ch, "_decide", decide)
    assert ch.tool_feedback(tmp_path, card.name, payload)
    assert ch.emit(tmp_path, card, payload)
    original = ch._load(ch._path(tmp_path, card))["exception"]
    clock[0] = 1120
    assert ch.tool_feedback(tmp_path, card.name, payload)
    assert not ch.emit(tmp_path, card, payload)
    assert ch._load(ch._path(tmp_path, card))["exception"] == original
    assert len(decisions) == 1
    clock[0] = 1600
    assert ch.emit(tmp_path, card, payload)
    assert len(decisions) == 2


def test_nudge_configuration_and_override():
    import pytest
    from shantytown import session_budget as sb
    cfg = sb.parse({"context_threshold_pct": 70, "context_nudge_pct": 40,
                    "context_nudge_repeat_seconds": 90,
                    "context_by_role": {"administrator": {"context_nudge_pct": 35}}})
    assert cfg.context_for("administrator", "reader").nudge_at == 35
    assert cfg.context_for("administrator", "reader").repeat_seconds == 90
    for value in (True, 0, 70, float("nan")):
        with pytest.raises(sb.BudgetError):
            sb.parse({"context_threshold_pct": 70, "context_nudge_pct": value})
    for value in (True, 0, 1.5, 3601):
        with pytest.raises(sb.BudgetError):
            sb.parse({"context_nudge_repeat_seconds": value})
    assert sb.parse({}).context is None


def test_tool_nudge_reset_identity_hard_and_unknown(tmp_path, monkeypatch, capsys):
    card, payload = world(tmp_path, "administrator")
    (tmp_path / "crew").mkdir()
    (tmp_path / "crew/reader.json").write_text('{"role":"administrator"}')
    payload["hook_event_name"] = "PostToolUse"
    monkeypatch.setattr(ch.time, "time", lambda: 1000)
    turn(payload["transcript_path"], 550)
    assert ch.tool_feedback(tmp_path, card.name, payload)
    assert not ch.tool_feedback(tmp_path, card.name, payload)
    turn(payload["transcript_path"], 600)  # +5 points despite no elapsed time
    assert ch.tool_feedback(tmp_path, card.name, payload)
    turn(payload["transcript_path"], 540)
    assert not ch.tool_feedback(tmp_path, card.name, payload)
    turn(payload["transcript_path"], 550)
    assert ch.tool_feedback(tmp_path, card.name, payload)
    payload["session_id"] = "new"
    assert ch.tool_feedback(tmp_path, card.name, payload)
    turn(payload["transcript_path"], 750)
    capsys.readouterr()
    assert ch.tool_feedback(tmp_path, card.name, payload)
    assert "HARD HANDOFF" in capsys.readouterr().out
    turn(payload["transcript_path"], 1001)
    assert not ch.tool_feedback(tmp_path, card.name, payload)
    payload["session_id"] = None
    assert not ch.tool_feedback(tmp_path, card.name, payload)
    assert not ch.tool_feedback(tmp_path, "../reader", payload)
    payload["hook_event_name"] = "PreToolUse"
    assert not ch.tool_feedback(tmp_path, card.name, payload)


def test_disabled_hint_does_not_create_state(tmp_path):
    from shantytown.protocols import Agent
    card = Agent(name="reader", role="administrator")
    assert not ch.emit(tmp_path, card, {})
    ch.session_start(tmp_path, card, {})
    assert not (tmp_path / "context_budget").exists()


def test_concurrent_tool_observation_never_waits_or_loses_stop_exception(tmp_path, monkeypatch):
    import fcntl
    card, payload = world(tmp_path, "administrator")
    (tmp_path / "crew").mkdir()
    (tmp_path / "crew/reader.json").write_text('{"role":"administrator"}')
    payload["hook_event_name"] = "PostToolUse"
    monkeypatch.setattr(ch, "_decide", lambda *a: dict(decision="continue", reason="safe operation"))
    assert ch.emit(tmp_path, card, payload)
    saved = ch._load(ch._path(tmp_path, card))
    with open(str(ch._path(tmp_path, card)) + ".lock", "r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert not ch.tool_feedback(tmp_path, card.name, payload)
    assert ch._load(ch._path(tmp_path, card)) == saved
    assert ch.tool_feedback(tmp_path, card.name, payload)
    assert ch._load(ch._path(tmp_path, card))["exception"] == saved["exception"]


def admin_milestones(tmp_path):
    card, payload = world(tmp_path, "administrator")
    (tmp_path / "shantytown.toml").write_text(
        '[session_budget]\ncontext_window=1000000\n'
        '[session_budget.context_by_role.administrator]\n'
        'context_nudge_pct=25\ncontext_nudge_step_pct=10\n')
    (tmp_path / "crew").mkdir()
    (tmp_path / "crew/reader.json").write_text('{"role":"administrator"}')
    payload["hook_event_name"] = "PostToolUse"
    return card, payload


def test_admin_original_incident_boundary_and_milestones(tmp_path, monkeypatch, capsys):
    card, payload = admin_milestones(tmp_path)
    clock = [1000]
    monkeypatch.setattr(ch.time, "time", lambda: clock[0])
    monkeypatch.setattr(ch, "_decide", lambda *a: (_ for _ in ()).throw(
        AssertionError("tool feedback must not call Jev")))
    # Scoped boundary controls, not a fabricated replay of all 430 source points.
    for tokens, expected in [
        (249999, False), (250000, True), (260801, False), (261046, False),
        (349999, False), (350000, True), (450000, True),
        (500000, False), (549999, False), (550000, True),
        (650000, True), (750000, True),
    ]:
        turn(payload["transcript_path"], tokens)
        clock[0] += 1000  # time alone never substitutes for the +10% milestone
        assert ch.tool_feedback(tmp_path, card.name, payload) is expected
        capsys.readouterr()
    assert not (tmp_path / "notify/cycle-requests.json").exists()
    assert not (tmp_path / "context-decisions.jsonl").exists()


def test_admin_late_sample_reset_and_stop_independence(tmp_path, monkeypatch, capsys):
    card, payload = admin_milestones(tmp_path)
    monkeypatch.setattr(ch.time, "time", lambda: 1000)
    for tokens, expected in [(260801, True), (349999, False), (350000, True),
                             (15134, False), (250000, True)]:
        turn(payload["transcript_path"], tokens)
        assert ch.tool_feedback(tmp_path, card.name, payload) is expected
        capsys.readouterr()
    # Tool feedback does not consume the separate Stop preparation milestone.
    assert ch.emit(tmp_path, card, payload)
    capsys.readouterr()
    assert not ch.emit(tmp_path, card, payload)
    turn(payload["transcript_path"], 350000)
    assert ch.emit(tmp_path, card, payload)
    capsys.readouterr()
    payload["session_id"] = "next-session"
    assert ch.tool_feedback(tmp_path, card.name, payload)


def test_admin_step_validation_inheritance_and_worker_policy():
    import pytest
    from shantytown import session_budget as sb
    cfg = sb.parse({"context_window": 1000000, "context_by_role": {
        "administrator": {"context_nudge_pct": 25, "context_nudge_step_pct": 10}}})
    assert cfg.context_for("administrator").nudge_step_pct == 10
    assert cfg.context_for("administrator").nudge_at == 25
    worker = cfg.context_for("worker")
    assert worker.nudge_step_pct is None
    assert worker.nudge_at == 35
    assert worker.repeat_seconds == 120
    assert sb.parse({"context_by_agent": {"reader": {
        "context_nudge_step_pct": 10}}}).context_for("worker", "reader").window is None
    for value in (True, 0, -1, 100, float("nan"), float("inf"), "10"):
        with pytest.raises(sb.BudgetError, match="context_nudge_step_pct"):
            sb.parse({"context_nudge_step_pct": value})
