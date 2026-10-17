"""Explicit routine Stop-wake cadence, never a token or quota ceiling.

No provider arithmetic: consume the dispatch governor's fresh lane verdict.
No activation by default. An unreadable clock or signal cannot withhold work.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Policy:
    mode: str = "off"
    agents: tuple[str, ...] = ()


def interval(pct: float | None) -> float:
    """Declared admin cadence in seconds; independent of worker admission."""
    if pct is None or not math.isfinite(pct) or not 0 <= pct <= 100:
        return 0
    return 900 if pct >= 90 else 300 if pct >= 80 else 0


def remaining(pct: float | None, elapsed: float | None) -> float:
    if elapsed is None or not math.isfinite(elapsed) or elapsed < 0:
        return 0
    return max(0.0, interval(pct) - elapsed)


def parse(tbl: dict) -> Policy:
    """Deployment must name participants; no inferred account membership."""
    unknown = set(tbl) - {"mode", "agents"}
    if unknown:
        raise ValueError("admin_wake_budget: unknown key " + sorted(unknown)[0])
    mode, agents = tbl.get("mode", "off"), tbl.get("agents", [])
    if mode not in ("off", "advise", "enforce"):
        raise ValueError("admin_wake_budget.mode must be off, advise or enforce")
    if not isinstance(agents, list) or any(not isinstance(a, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", a) for a in agents):
        raise ValueError("admin_wake_budget.agents must be a list of names")
    if mode != "off" and not agents:
        raise ValueError("admin_wake_budget requires explicit agents")
    return Policy(mode, tuple(agents))


def record(root, inp, verdict, *, now=None):
    """One bounded local snapshot/counters, never a model wake or a graph call.

    External/operator prompts do not traverse Stop policy, so that count remains
    UNKNOWN rather than falsely zero. No transcript or event body is persisted.
    """
    import json
    import sys
    import time
    from pathlib import Path
    from .files import write_json_atomic

    wait = remaining(inp.admin_usage_pct, inp.admin_wake_elapsed)
    state = ("urgent-bypass" if inp.urgent else
             "held" if verdict.by == "admin-wake-budget" else
             "would-hold" if wait and verdict.block else
             "routine-wake" if verdict.block else "idle")
    path = Path(root) / "admin-wake-budget" / f"{inp.me}.json"
    try:
        import fcntl
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if path.exists():
                prior = json.loads(path.read_text())
                counts = prior.get("counts") if isinstance(prior, dict) else None
                allowed = {"urgent-bypass", "held", "would-hold", "routine-wake", "idle"}
                if (not isinstance(counts, dict)
                        or any(k not in allowed or type(v) is not int or v < 0
                               for k, v in counts.items())):
                    raise ValueError("counter history UNKNOWN")
                counts = dict(counts)
            else:
                counts = {}
            counts[state] = counts.get(state, 0) + 1
            path.parent.mkdir(parents=True, exist_ok=True)
            write_json_atomic(path, {"mode": inp.admin_wake_mode, "state": state,
                "observed_at": time.time() if now is None else now,
                "seven_day_pct": inp.admin_usage_pct,
                "remaining_seconds": wait, "counts": counts,
                "operator_bypasses": None, "operator_coverage": "UNKNOWN",
                "scope": "routine Stop wakes only; no ongoing-turn token bound"})
    except (OSError, ValueError, TypeError):
        print("admin_wake_budget: counter write UNKNOWN", file=sys.stderr)
    print(f"admin_wake_budget: {inp.admin_wake_mode} {state}; "
          f"routine wait={wait:.0f}s; operator count UNKNOWN", file=sys.stderr)


def prompt(root, agent):
    """Count unclassified external submissions without reading prompt stdin.

    Human/operator and injected messages share this boundary: count ALL of them
    as bypasses, but never claim an authenticated operator identity.
    """
    import fcntl
    import json
    import time
    from pathlib import Path
    from . import config
    from .files import FilesRegistry, write_json_atomic

    cfg, error = config.load_or_default(root)
    policy = cfg.admin_wake_budget
    if error or policy.mode == "off" or agent not in policy.agents:
        return
    card = FilesRegistry(Path(root) / "crew").get(agent)
    if card.role != "administrator":
        return
    directory = Path(root) / "admin-wake-budget"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{agent}.external.json"
    with (directory / f"{agent}.external.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if path.exists():
            prior = json.loads(path.read_text())
            count = prior.get("external_prompt_bypasses") if isinstance(prior, dict) else None
            if type(count) is not int or count < 0:
                raise ValueError("counter history UNKNOWN")
        else:
            count = 0
        write_json_atomic(path, {"external_prompt_bypasses": count + 1,
            "observed_at": time.time(), "operator_identity": "UNKNOWN",
            "coverage": "UserPromptSubmit only; no prompt content read"})


def main(argv=None):
    import argparse
    import os
    import sys
    from pathlib import Path
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", required=True, type=Path)
    args = ap.parse_args(argv)
    try:
        prompt(args.root, os.environ.get("SHANTY_AGENT", ""))
    except Exception as exc:  # hook must never obstruct operator work
        print(f"admin_wake_budget: external counter UNKNOWN ({type(exc).__name__})",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
