"""The overflow job lane (aegis-za4f.14): Claude stays the default; codex takes
roadmap task jobs only once Claude's seven_day window passes 70% before
Friday, until that window resets. Every rule is also shown saying no."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from shantytown import cli, config
from shantytown import ephemeral as eph

from test_ephemeral import _st, store  # noqa: F401

# Fixed calendar days (UTC) so the Friday cutoff is tested, not assumed.
TUE = datetime(2026, 11, 24, 12, tzinfo=timezone.utc).timestamp()
FRI = datetime(2026, 11, 27, 12, tzinfo=timezone.utc).timestamp()
SAT = datetime(2026, 11, 28, 12, tzinfo=timezone.utc).timestamp()
RESET = datetime(2026, 11, 30, 9, tzinfo=timezone.utc).timestamp()
NEXT_RESET = RESET + 7 * 86400


def _decide(pct, now, latch=None, reset_at=RESET, lost=""):
    return eph.overflow_decision(pct=pct, reset_at=reset_at, lost=lost, now=now,
                                 latch=latch, threshold=70, cutoff_weekday=4)


def _on_policy(**kw):
    return config.Ephemeral(overflow={"enabled": True, "harness": "codex",
                                      "threshold_pct": 70, "cutoff_weekday": 4,
                                      "lane": "", **kw})


# --- the switch rule ------------------------------------------------------------

def test_over_threshold_before_friday_turns_overflow_on_and_latches():
    v = _decide(71, TUE)
    assert v.on and "71% >= 70% on Tuesday" in v.why
    assert v.latch["reset_at"] == RESET


def test_under_threshold_stays_off():
    v = _decide(69, TUE)
    assert not v.on and v.latch is None and "69% < 70%" in v.why


def test_crossing_on_friday_or_later_does_not_turn_it_on():
    for now in (FRI, SAT):
        v = _decide(90, now)
        assert not v.on and v.latch is None and "not before Friday" in v.why


def test_a_latched_window_stays_on_past_friday_even_if_usage_reads_lower():
    latch = _decide(75, TUE).latch
    v = _decide(40, SAT, latch=latch)
    assert v.on and "holds until the window resets" in v.why


def test_the_window_resetting_turns_it_off_and_clears_the_latch():
    latch = _decide(75, TUE).latch
    # The producer now reports next week's reset: a new window, under threshold.
    v = _decide(5, RESET + 3600, latch=latch, reset_at=NEXT_RESET)
    assert not v.on and v.latch is None
    # Same reset timestamp but its moment has passed: also a reset.
    v = _decide(5, RESET + 1, latch=latch)
    assert not v.on and v.latch is None


def test_an_unusable_reading_keeps_jobs_on_the_default_lane():
    v = _decide(95, TUE, lost="probe failed")
    assert not v.on and "unusable (probe failed)" in v.why
    assert not _decide(None, TUE).on
    v = _decide(95, TUE, reset_at=None)
    assert not v.on and "no seven_day reset time" in v.why


def test_cutoff_weekday_7_means_no_cutoff():
    v = eph.overflow_decision(pct=80, reset_at=RESET, lost="", now=SAT, latch=None,
                              threshold=70, cutoff_weekday=7)
    assert v.on


# --- scope ---------------------------------------------------------------------

def test_only_roadmap_task_jobs_with_no_explicit_harness_may_overflow():
    p = _on_policy()
    assert eph.overflow_applies(eph.Request(job="task", item="i"), p)
    assert eph.overflow_applies(eph.Request(job="task", item="i", track="roadmap"), p)
    for req in (eph.Request(job="task", item="i", track="ops"),
                eph.Request(job="task", item="i", track="short-term"),
                eph.Request(job="task", item="i", track="backlog"),
                eph.Request(job="review", item="i", repo="o/n", pr=1),
                eph.Request(job="merge", item="i", repo="o/n", pr=1),
                eph.Request(job="triage", item="i"),
                eph.Request(job="task", item="i", harness="claude")):
        assert not eph.overflow_applies(req, p), req


def test_overflow_is_off_unless_enabled():
    req = eph.Request(job="task", item="i")
    assert not eph.overflow_applies(req, config.Ephemeral())
    assert not eph.overflow_applies(req, _on_policy(enabled=False))


def test_a_task_lane_already_on_the_overflow_harness_has_nothing_to_overflow():
    p = config.Ephemeral(harness_by_job={"task": "codex"},
                         overflow={"enabled": True, "harness": "codex"})
    assert not eph.overflow_applies(eph.Request(job="task", item="i"), p)


# --- config --------------------------------------------------------------------

def test_config_reads_the_overflow_table_and_refuses_typos(tmp_path):
    toml = tmp_path / "shantytown.toml"
    toml.write_text("[ephemeral]\n")
    assert config.load(tmp_path).ephemeral.overflow == {}
    toml.write_text("[ephemeral.overflow]\nenabled = true\n")
    assert config.load(tmp_path).ephemeral.overflow == {
        "enabled": True, "harness": "codex", "threshold_pct": 70,
        "cutoff_weekday": 4, "lane": ""}
    for bad, match in (("enabeld = true", "unknown key"),
                       ("enabled = \"yes\"", "enabled must be true or false"),
                       ("threshold_pct = 0", "threshold_pct"),
                       ("threshold_pct = 101", "threshold_pct"),
                       ("cutoff_weekday = 8", "cutoff_weekday")):
        toml.write_text(f"[ephemeral.overflow]\n{bad}\n")
        with pytest.raises(config.ConfigError, match=match):
            config.load(tmp_path)


# --- end to end through `st agent spawn` ------------------------------------------

def _overflow_toml(root, extra=""):
    (root / "shantytown.toml").write_text(
        "[ephemeral]\nmax_agents = 1\nunattended = false\nrequire_verified_identity = true\n"
        "[ephemeral.overflow]\nenabled = true\n" + extra)


def test_spawn_routes_a_roadmap_task_to_codex_while_ops_stays_on_claude(
        store, monkeypatch, capsys):
    root, _panes, launched = store
    _overflow_toml(root)
    monkeypatch.setattr(eph, "kick_drain", lambda r: None)
    monkeypatch.setattr(cli, "_overflow_lane_reading", lambda a, p: (82.0, RESET, ""))
    monkeypatch.setattr(eph, "overflow_decision",
                        lambda **kw: eph.Overflow(True, "test: over", {"reset_at": RESET}))
    # Fill the one slot with ops work: it is not roadmap, so Claude carries it.
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-ops",
               "--track", "ops") == cli.OK
    assert launched and eph.live(root)[0]["harness"] == "claude"
    # A roadmap task (the default track) now queues on codex, not claude.
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-road") == cli.OK
    err = capsys.readouterr().err
    assert "overflow ON: test: over; task on it-road routed to codex instead of claude" in err
    (t,) = eph.tickets(root)
    assert (t["item"], t["harness"]) == ("it-road", "codex")
    assert eph.read_overflow_latch(root) == {"reset_at": RESET}


def test_spawn_with_overflow_off_keeps_the_roadmap_task_on_claude(store, monkeypatch, capsys):
    root, _panes, launched = store
    _overflow_toml(root)
    monkeypatch.setattr(eph, "kick_drain", lambda r: None)
    monkeypatch.setattr(cli, "_overflow_lane_reading", lambda a, p: (31.0, RESET, ""))
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-1") == cli.OK
    assert eph.live(root)[0]["harness"] == "claude"
    assert "overflow off: default lane seven_day 31% < 70%" in capsys.readouterr().err
    assert eph.read_overflow_latch(root) is None


def test_spawn_overflow_stays_on_claude_when_codex_is_capped_off(store, monkeypatch, capsys):
    root, _panes, _launched = store
    _overflow_toml(root, "[ephemeral.max_agents_by_harness]\ncodex = 0\n")
    monkeypatch.setattr(cli, "_overflow_lane_reading", lambda a, p: (99.0, RESET, ""))
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-1") == cli.OK
    assert eph.live(root)[0]["harness"] == "claude"
    assert "codex is capped at 0" in capsys.readouterr().err


def test_spawn_overflow_fails_toward_claude_when_the_governor_breaks(store, monkeypatch, capsys):
    root, _panes, _launched = store
    _overflow_toml(root)

    def broken(a, p):
        raise RuntimeError("no governor")
    monkeypatch.setattr(cli, "_overflow_lane_reading", broken)
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-1") == cli.OK
    assert eph.live(root)[0]["harness"] == "claude"
    assert "governor unreadable (RuntimeError)" in capsys.readouterr().err


def test_the_lane_reading_reports_a_missing_governor_as_lost(tmp_path):
    (tmp_path / "shantytown.toml").write_text("[ephemeral.overflow]\nenabled = true\n")
    a = cli._parse_args(["--root", str(tmp_path), "agent", "spawn", "--list"])
    a.root = tmp_path
    pct, reset_at, lost = cli._overflow_lane_reading(a, config.load(tmp_path).ephemeral)
    assert (pct, reset_at) == (None, None) and "no usage governor for the claude lane" in lost


def test_a_latch_survives_a_dark_probe_until_its_own_reset_time():
    latch = _decide(75, TUE).latch
    v = _decide(None, SAT, latch=latch, reset_at=None, lost="probe failed")
    assert v.on and v.latch == latch
    v = _decide(None, RESET + 1, latch=latch, reset_at=None, lost="probe failed")
    assert not v.on and v.latch is None
