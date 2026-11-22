"""Per-job harness session id, model and token usage for the ephemeral ledger.

Captured once, when the job's result is first written (its report, or a forced
teardown). Reading never fails the ending: an unreadable or absent transcript is
recorded as ``state: "unknown"`` with the reason, never as zero usage.

Where the transcripts are:
- codex jobs: ``$XDG_STATE_HOME/shantytown/codex/<job>/sessions`` (the durable
  sessions link the launcher makes), filtered to rollouts whose ``session_meta``
  cwd is the job workspace.
- claude jobs: ``~/.claude/projects/<encoded workspace>/*.jsonl``. Each job has
  its own workspace, so this directory is the job's alone.
"""
from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import time

MAX_SESSIONS = 8
_FIELDS = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens",
           "output_tokens", "reasoning_output_tokens", "total_tokens")


def _codex_meta(path: Path) -> tuple[str | None, str | None, str | None]:
    """(session id, cwd, last model) from a codex rollout."""
    sid = cwd = model = None
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"session_meta"' not in line and '"turn_context"' not in line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            payload = rec.get("payload") if isinstance(rec, dict) else None
            if not isinstance(payload, dict):
                continue
            if rec.get("type") == "session_meta":
                sid = payload.get("id") if isinstance(payload.get("id"), str) else sid
                cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else cwd
            elif rec.get("type") == "turn_context" and isinstance(payload.get("model"), str):
                model = payload["model"]
    return sid, cwd, model


def _claude_model(path: Path) -> str | None:
    model = None
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"model"' not in line:
                continue
            try:
                msg = (json.loads(line).get("message") or {})
            except (ValueError, AttributeError):
                continue
            if isinstance(msg, dict) and isinstance(msg.get("model"), str):
                model = msg["model"]
    return model


def _sessions(rec: dict, home: Path, state_base: Path):
    from .harness import get as harness_get
    from .stats import _claude_project_dir
    harness, workspace = rec.get("harness"), rec.get("workspace")
    if not workspace or harness not in ("claude", "codex"):
        raise LookupError(f"usage capture does not support harness {harness!r}")
    reader = harness_get(harness)
    if harness == "codex":
        base = state_base / "shantytown" / "codex" / rec["name"] / "sessions"
        for path in sorted(base.glob("*/*/*/*.jsonl")):
            sid, cwd, model = _codex_meta(path)
            if cwd == str(workspace):
                yield sid or path.stem, model, reader.read_usage(path)
    else:
        base = home / ".claude" / "projects" / _claude_project_dir(str(workspace))
        for path in sorted(base.glob("*.jsonl")):
            yield path.stem, _claude_model(path), reader.read_usage(path)


def collect(rec: dict, *, home: Path | None = None, state_base: Path | None = None,
            now: float | None = None) -> dict:
    home = Path(home) if home is not None else Path.home()
    state_base = Path(state_base) if state_base is not None else Path(
        os.environ.get("XDG_STATE_HOME", home / ".local" / "state"))
    out = {"captured_at": time.time() if now is None else now, "harness": rec.get("harness")}
    try:
        found = list(_sessions(rec, home, state_base))
    except (LookupError, OSError, ValueError) as error:
        return dict(out, state="unknown", reason=str(error)[:200])
    if not found:
        return dict(out, state="unknown", reason="no transcript found for the job workspace")
    sessions, totals, unknown = [], dict.fromkeys(_FIELDS, 0), 0
    for sid, model, usage in found[:MAX_SESSIONS]:
        values = asdict(usage) if usage is not None else None
        sessions.append({"id": sid, "model": model, "usage": values})
        if values is None:
            unknown += 1
            continue
        for key in _FIELDS:
            totals[key] += values[key]
    if unknown == len(sessions):
        # A transcript with no usage record is UNKNOWN usage, never zero.
        return dict(out, state="unknown", reason="transcripts carry no usage record",
                    sessions=sessions, totals=None, truncated=len(found) > MAX_SESSIONS)
    return dict(out, state="known" if not unknown else "partial",
                sessions=sessions, totals=totals,
                truncated=len(found) > MAX_SESSIONS)
