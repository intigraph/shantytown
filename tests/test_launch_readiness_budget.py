"""Slow healthy daemon startup must not make a cycle destroy its session."""
from types import SimpleNamespace

import pytest

from shantytown import cli, codex_ready, cycle
from shantytown.protocols import Agent
from shantytown.tmux import NullPanes


def observer(monkeypatch, ready_at):
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(cli, "time", SimpleNamespace(
        sleep=lambda seconds: setattr(clock, "now", clock.now + seconds)))
    panes = NullPanes(live={"fixture"})
    runtime = SimpleNamespace(is_live=lambda screen: clock.now >= ready_at)
    return clock, panes, runtime


@pytest.mark.parametrize("ready_at", [6.0, codex_ready.TIMEOUT + 1.0])
def test_slow_connect_keeps_cycle_session(monkeypatch, ready_at):
    clock, panes, runtime = observer(monkeypatch, ready_at)
    card = Agent(name="fixture", role="worker", harness="codex")
    launches = []

    def launch(a, card, panes, runtime, **kw):
        launches.append(kw)
        panes.respawn("fixture")
        return cli.OK if cli._observe_live(runtime, panes, "fixture", card) else cli.CANNOT_TELL

    monkeypatch.setattr(cli, "_launch", launch)
    monkeypatch.setattr(cli, "_foreign_session_refusal", lambda *a: None)
    monkeypatch.setattr(cli, "_capture_history_before_kill", lambda *a: None)
    # Crossing into either fallback gate is the actual incident, not just a
    # different timeout number. Fail before any fallback side effects.
    def fallback(*a, **kw):
        pytest.fail("healthy delayed launch entered destructive fallback")
    monkeypatch.setattr(cli, "_launch_admitted", fallback)
    monkeypatch.setattr(cli, "_cmd_stop", fallback)
    result = cli._restart_cycle(SimpleNamespace(), card, "fixture", "fixture",
                                panes, runtime, cycle.Plan(cycle.RESPAWN, "fixture"), None)
    assert result == (cli.OK, cycle.RESPAWN)
    assert launches == [{"reuse_session": True}]
    assert panes.exists("fixture")
    assert clock.now == ready_at


@pytest.mark.parametrize("harness,bound", [("codex", codex_ready.TIMEOUT + 5), ("claude", 5)])
def test_never_ready_stays_unknown_and_bounded(monkeypatch, harness, bound):
    clock, panes, runtime = observer(monkeypatch, float("inf"))
    card = Agent(name="fixture", role="worker", harness=harness)
    assert not cli._observe_live(runtime, panes, "fixture", card)
    assert bound <= clock.now <= bound + cli._LIVE_DELAY


def test_budget_follows_readiness_constant(monkeypatch):
    monkeypatch.setattr(codex_ready, "TIMEOUT", 30.0)
    clock, panes, runtime = observer(monkeypatch, 31.0)
    card = Agent(name="fixture", role="worker", harness="codex")
    assert cli._observe_live(runtime, panes, "fixture", card)
    assert clock.now == 31.0


# aegis-j550: opencode's measured cold start (4.2s warm, more for a job) sits at
# the edge of the shared ~5s window, so a healthy job launch was ended as
# "never observed live". The harness declares its own allowance.
def test_opencode_slow_start_is_observed_live(monkeypatch):
    clock, panes, runtime = observer(monkeypatch, 6.0)
    card = Agent(name="fixture", role="worker", harness="opencode")
    assert cli._observe_live(runtime, panes, "fixture", card)
    assert clock.now == 6.0


def test_claude_window_is_unchanged_by_opencode_allowance(monkeypatch):
    clock, panes, runtime = observer(monkeypatch, 6.0)
    card = Agent(name="fixture", role="worker", harness="claude")
    assert not cli._observe_live(runtime, panes, "fixture", card)


def test_opencode_never_ready_stays_bounded(monkeypatch):
    from shantytown import harness
    allowance = harness.get("opencode").startup_allowance_s
    assert allowance > 0
    clock, panes, runtime = observer(monkeypatch, float("inf"))
    card = Agent(name="fixture", role="worker", harness="opencode")
    assert not cli._observe_live(runtime, panes, "fixture", card)
    assert 5 + allowance <= clock.now <= 5 + allowance + cli._LIVE_DELAY
