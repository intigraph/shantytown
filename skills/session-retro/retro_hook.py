#!/usr/bin/env python3
"""session-retro — a Stop hook that harvests improvement issues, ONCE per session.

THE CENTRAL PROBLEM this script exists to solve:

    A Claude Code "Stop" hook does NOT fire at session end. It fires at EVERY
    turn boundary — every single time the agent finishes a response. A retro
    that fires on every Stop fires dozens of times an hour and is pure spam.

So the whole job of this file is de-duplication: fire the retrospective AT MOST
ONCE per session (or once per N hours), and make every other Stop in that session
a silent no-op. Two independent guards do it:

    1. `stop_hook_active` — Claude Code sets this true on the Stop that was itself
       triggered by a previous blocking hook. If it's true, we already fired and
       the model is mid-retro; exit 0 immediately (also prevents an infinite loop).
    2. a per-session marker file — durable across the reset of `stop_hook_active`.
       If the marker for this session_id exists, we've fired; exit 0.

FAIL OPEN, ALWAYS. A retro hook that wedges an agent's stop is worse than no
retro. Every error path — bad stdin, missing jq/keys, unwritable state dir,
anything — ends in `exit 0` with NO output, so the stop proceeds normally. The
hook only ever *blocks* on the one deliberate, de-duplicated path.

Mechanism for soliciting the retro: on the fire path we print
`{"decision":"block","reason": <prompt>}` to stdout and exit 0. Claude Code feeds
`reason` back to the model as one more turn — the model runs the retro and files
the improvement issues itself (see file_improvement.py / the SKILL). The Stop that
follows *that* turn is caught by guard 1 and/or guard 2, so it does not re-fire.

Stdlib only. No dependencies. Config is env vars (see the SKILL / --help note).
"""

import json
import os
import shutil
import subprocess
import sys
import time
import pathlib


def _state_dir() -> pathlib.Path:
    # Robust to the dir not existing yet — this is the common first-run case.
    d = os.environ.get("RETRO_STATE_DIR") or os.path.join(
        os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
        "session-retro",
    )
    p = pathlib.Path(d)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _interval_hours() -> float:
    try:
        return float(os.environ.get("RETRO_MIN_INTERVAL_HOURS", "0") or "0")
    except ValueError:
        return 0.0


def _dp_signal() -> str:
    """OPTIONAL: surface desirepath's recorded FAILED tool calls as pre-identified
    improvement candidates. dp (github.com/scbrown/desire-path) records the
    capabilities something reached for that did not exist — and a RECURRING failed
    tool call IS an improvement issue ("X was reached for N times and does not
    exist — add it, or an alias that routes to what does").

    Self-hiding, like every other tool this skill reaches for: returns "" when dp
    is absent, errors, times out, or has nothing — a machine without dp gets the
    plain retro, never an error. Reads dp's published JSON, not its SQLite."""
    if not shutil.which("dp"):
        return ""
    try:
        r = subprocess.run(["dp", "paths", "--top", "5", "--json"],
                           capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return ""
        paths = json.loads(r.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return ""
    if not isinstance(paths, list):
        return ""
    rows = [f"   - {p['pattern']} (reached for {p['count']}x)"
            for p in paths
            if isinstance(p, dict) and p.get("pattern") and p.get("count")]
    if not rows:
        return ""
    return (
        "\n\n3. desirepath (dp) recorded these FAILED tool calls — capabilities "
        "something reached for that did not exist. Each RECURRING one is its own "
        "improvement issue; file the real gaps, skip one-off typos:\n"
        + "\n".join(rows)
    )


def _prompt() -> str:
    # The retrospective solicitation. Override wholesale with RETRO_PROMPT_FILE.
    override = os.environ.get("RETRO_PROMPT_FILE")
    if override and os.path.isfile(override):
        try:
            return pathlib.Path(override).read_text()
        except OSError:
            pass
    return (
        "Session wrap-up retrospective (do this once, briefly, then stop).\n\n"
        "1. In 2-4 honest sentences: what actually slowed this session down? Be "
        "specific and self-critical — dead ends, missing context, slow tools, "
        "things you had to rediscover.\n\n"
        "2. Then FILE IMPROVEMENT ISSUES for anything that, had it existed, would "
        "have made THIS session faster or better. Look across these areas — skip "
        "any that don't apply, don't invent filler:\n"
        "   - session speed / work throughput (what made you slow?)\n"
        "   - token & context-limit friction (what burned context? what got "
        "re-read or re-explained?)\n"
        "   - information accessibility (a fact/doc/answer that was hard to find "
        "or didn't exist)\n"
        "   - the environment & its processes (tooling gaps, flaky steps, missing "
        "automation, unclear runbooks)\n"
        "   - improvements to the operator's own code projects you touched\n\n"
        "File each as a separate issue using your tracker (see the session-retro "
        "SKILL for the backend, or run this skill's file_improvement.py). Use this "
        "shape for every one:\n\n"
        "   Title: <imperative, specific — 'Cache X so it isn't re-fetched per run'>\n"
        "   What slowed me down: <the concrete friction you hit this session>\n"
        "   Proposed fix: <the smallest change that removes it>\n"
        "   Where: <which repo / system / doc it belongs to>\n\n"
        + _dp_signal()
        + "\n\nIf nothing genuinely rose to the bar, say so in one line and file "
        "nothing — an empty retro beats a padded one. Then stop."
    )


def main() -> int:
    # --- fail-open umbrella: nothing below may raise past here -------------
    try:
        if os.environ.get("RETRO_DISABLE"):
            return 0

        raw = sys.stdin.read() if not sys.stdin.isatty() else ""
        payload = {}
        if raw.strip():
            try:
                payload = json.loads(raw)
            except (ValueError, TypeError):
                payload = {}

        # Guard 1: we're already inside the retro turn we triggered. Do not loop.
        if payload.get("stop_hook_active"):
            return 0

        sid = str(payload.get("session_id") or "").strip()
        st = _state_dir()

        # Guard 2a: per-session marker. If we've fired for this session, no-op.
        if sid:
            marker = st / f"session-{sid}.done"
            if marker.exists():
                return 0
        else:
            # No session_id available — fall back to a per-day marker so we still
            # de-dup instead of firing on every turn.
            marker = st / f"day-{time.strftime('%Y%m%d')}.done"
            if marker.exists():
                return 0

        # Guard 2b: optional global rate limit across sessions.
        hours = _interval_hours()
        if hours > 0:
            last = st / "last-fired"
            if last.exists() and (time.time() - last.stat().st_mtime) < hours * 3600:
                return 0

        # --- FIRE. Record first, so a crash mid-emit still de-dups next time. --
        try:
            marker.write_text(str(int(time.time())))
            (st / "last-fired").write_text(str(int(time.time())))
        except OSError:
            # Can't record → can't guarantee once-per-session → better to stay
            # silent than to risk firing every turn. Fail open, no block.
            return 0

        print(json.dumps({"decision": "block", "reason": _prompt()}))
        return 0
    except Exception:
        # Absolute backstop: never wedge a stop. No output => stop proceeds.
        return 0


if __name__ == "__main__":
    sys.exit(main())
