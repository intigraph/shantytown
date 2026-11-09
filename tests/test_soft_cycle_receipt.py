"""Stop continuation is not a session reset; no real pane or hook is invoked."""
import argparse
import json
import time

import pytest

from shantytown import cli, cycle, soft_cycle
from shantytown.protocols import Agent


def hook(root, session="old", transcript="old.jsonl", at=None):
    path = root / "context_budget" / "worker.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(dict(payload=dict(session_id=session,
        transcript_path=transcript), at=time.time() if at is None else at)))


def test_pending_intent_is_not_sent_twice_and_late_session_completes(tmp_path):
    hook(tmp_path)
    attempt, send = soft_cycle.begin(tmp_path, "worker")
    assert send
    assert soft_cycle.begin(tmp_path, "worker") == (attempt, False)
    hook(tmp_path)  # same session keeps working after Stop blocked
    assert not soft_cycle.confirmed(tmp_path, "worker", attempt)
    hook(tmp_path, "new", "new.jsonl")
    assert soft_cycle.confirmed(tmp_path, "worker", attempt)
    soft_cycle.finish(tmp_path, "worker")
    assert not soft_cycle.pending(tmp_path, "worker")


@pytest.mark.parametrize("session,transcript", [("old", "old.jsonl"),
    ("new", "old.jsonl"), ("old", "new.jsonl")])
def test_both_independent_identity_fields_must_change(tmp_path, session, transcript):
    hook(tmp_path)
    attempt, _ = soft_cycle.begin(tmp_path, "worker")
    hook(tmp_path, session, transcript)
    assert not soft_cycle.confirmed(tmp_path, "worker", attempt)


def test_missing_stale_and_corrupt_observations_never_prove_clear(tmp_path):
    with pytest.raises(OSError):
        soft_cycle.begin(tmp_path, "worker")
    hook(tmp_path, at=time.time() - 1900)
    with pytest.raises(ValueError):
        soft_cycle.begin(tmp_path, "worker")
    hook(tmp_path)
    attempt, _ = soft_cycle.begin(tmp_path, "worker")
    hook(tmp_path, "new", "new.jsonl", at=attempt["sent_at"] - 1)
    assert not soft_cycle.confirmed(tmp_path, "worker", attempt)
    (tmp_path / "context_budget/worker.json").write_text("bad json")
    assert not soft_cycle.confirmed(tmp_path, "worker", attempt)
    assert soft_cycle.pending(tmp_path, "worker")


def test_ready_ui_with_missing_footer_does_not_prove_clear(tmp_path, monkeypatch, capsys):
    hook(tmp_path)
    cycle.Requests(tmp_path).request("worker", "durable checkpoint")
    sent = []
    class Panes:
        def send(self, pane, text): sent.append(text)
        def capture(self, pane): return "ready, no token footer"
    runtime = argparse.Namespace(shows_ready_ui=lambda _: True)
    args = argparse.Namespace(root=tmp_path)
    card = Agent(name="worker", dangerous=False)
    monkeypatch.setattr(cli, "_capture_history_before_kill", lambda *a: None)
    monkeypatch.setattr(cli, "_CLEAR_SETTLE_S", 0.01)
    monkeypatch.setattr(cli, "_CLEAR_POLL_S", 0)
    monkeypatch.setattr(cli.triage_mod, "mid_flight", lambda _: False)
    assert not cli._cycle_soft(args, card, "worker", "pane", Panes(), runtime)
    assert "did not settle" in capsys.readouterr().err
    assert cycle.Requests(tmp_path).pending()["worker"]
    assert not cli._cycle_soft(args, card, "worker", "pane", Panes(), runtime)
    assert len(sent) == 1
    hook(tmp_path, "new", "new.jsonl")
    monkeypatch.setattr(cli.harness_mod, "bypass_intact", lambda *a: True)
    assert cli._cycle_soft(args, card, "worker", "pane", Panes(), runtime)
    assert len(sent) == 1


def test_unknown_soft_outcome_does_not_restart_or_consume_request(tmp_path, monkeypatch):
    cycle.Requests(tmp_path).request("worker", "checkpoint")
    monkeypatch.setattr(cli, "_cycle_soft", lambda *a: False)
    monkeypatch.setattr(cli, "_restart_cycle", lambda *a: pytest.fail("must not restart"))
    chosen = cycle.Plan(cycle.SOFT, "test")
    rc, mode = cli._perform_cycle_locked(argparse.Namespace(root=tmp_path),
        Agent(name="worker"), "worker", "pane", None, None, chosen, None)
    assert rc == cli.CANNOT_TELL and mode == cycle.SOFT
    assert cycle.Requests(tmp_path).pending()["worker"]


def test_pending_clear_cannot_plan_a_busy_turn_restart(tmp_path):
    hook(tmp_path)
    soft_cycle.begin(tmp_path, "worker")
    class NoMutation:
        def exists(self, *args): pytest.fail("must only observe pending attempt")
    plan = cli._cycle_plan(argparse.Namespace(root=tmp_path),
        Agent(name="worker"), "pane", NoMutation(), None)
    assert plan.mode == cycle.SOFT


def test_corrupt_pending_attempt_is_preserved_and_never_retyped(tmp_path):
    path = tmp_path / "cycle-soft/worker.json"
    path.parent.mkdir()
    path.write_text('{"before":{},"sent_at":1}')
    with pytest.raises(ValueError):
        soft_cycle.begin(tmp_path, "worker")
    assert path.exists()
