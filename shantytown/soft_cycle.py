"""Local hook evidence for one in-flight clear; never infer completion from UI.

The caller holds cycle.lifecycle_lock. A timed-out send may still be queued:
retain its baseline so later passes only observe it, never type another clear.
"""
import json
import math
import re
import time
from pathlib import Path

from .files import write_json_atomic


def _path(root, agent):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", agent):
        raise ValueError("invalid cycle agent")
    return Path(root) / "cycle-soft" / f"{agent}.json"


def _read(path):
    with path.open("rb") as stream:
        raw = stream.read(16385)
    if len(raw) > 16384:
        raise ValueError("cycle observation exceeds bound")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("invalid cycle observation")
    return value


#: How old a hook identity row may be and still be read as the CURRENT session
#: without further evidence. Stop and PostToolUse write it, so an agent idle
#: longer than this (a request waiting for tend) has an older row.
FRESH_S = 1800


def _claude_transcript_current(transcript, at) -> bool:
    """An old row still names the live session when nothing newer was started.

    aegis-zxor: an idle agent's row ages past FRESH_S while its cycle request
    waits, and every serve attempt then failed "baseline unavailable" forever.
    Claude Code keeps one directory per workspace and starts a NEW .jsonl for
    every new session (launch or clear). So the row is current when its own
    transcript exists, was not written after the row (no unhooked turns), and
    no sibling transcript is newer. Other harnesses share date-based directories
    across agents, where "no newer sibling" proves nothing: refuse there.
    """
    path = Path(transcript)
    if "/.claude/projects/" not in path.as_posix() or path.suffix != ".jsonl":
        return False
    try:
        mtime = path.stat().st_mtime
        if mtime > at + 60:
            return False
        return not any(p != path and p.stat().st_mtime > mtime
                       for p in path.parent.glob("*.jsonl"))
    except OSError:
        return False


def snapshot(root, agent, *, now=None):
    """The exact agent's hook-fed identity; not a newest-file guess."""
    _path(root, agent)  # validate before composing any path
    row = _read(Path(root) / "context_budget" / f"{agent}.json")
    identity, at = row.get("payload"), row.get("at")
    if (not isinstance(identity, dict) or type(at) not in (int, float)
            or not math.isfinite(at)):
        raise ValueError("no hook session identity")
    if any(not isinstance(identity.get(k), str) or not identity[k]
           for k in ("session_id", "transcript_path")):
        raise ValueError("incomplete hook session identity")
    age = (time.time() if now is None else now) - at
    if age < 0 or (age > FRESH_S and not _claude_transcript_current(
            identity["transcript_path"], at)):
        raise ValueError(f"hook session identity is {int(age)}s old and its "
                         f"transcript cannot prove it is still current")
    return dict(identity=identity, at=at)


def begin(root, agent):
    path = _path(root, agent)
    if path.exists():
        row = _read(path)
        if (set(row) != {"before", "sent_at"} or not isinstance(row["before"], dict)
                or type(row["sent_at"]) not in (int, float)
                or not math.isfinite(row["sent_at"])
                or any(not isinstance(row["before"].get(k), str) or not row["before"][k]
                       for k in ("session_id", "transcript_path"))):
            raise ValueError("invalid pending clear; preserve for diagnosis")
        return row, False
    before = snapshot(root, agent)
    row = dict(before=before["identity"], sent_at=time.time())
    path.parent.mkdir(parents=True, exist_ok=True)
    # Persist intent BEFORE typing: an error after the key can be ambiguous.
    write_json_atomic(path, row)
    return row, True


def confirmed(root, agent, attempt):
    try:
        row = snapshot(root, agent)
        return (row["at"] >= attempt["sent_at"]
                and all(row["identity"][k] != attempt["before"].get(k)
                        for k in ("session_id", "transcript_path")))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def finish(root, agent):
    _path(root, agent).unlink()


def abandon(root, agent) -> bool:
    """Withdraw a recorded clear that was NEVER typed, or that no request owns.

    Only for a send refused before any keystroke (tmux copy-mode), an explicit
    cancel, or a marker older than every pending request. Keeping such a marker
    told every later pass to "observe" a clear that can never arrive (aegis-zxor).
    """
    try:
        _path(root, agent).unlink()
        return True
    except FileNotFoundError:
        return False


def sent_at(root, agent):
    """When the recorded clear was attempted; None when absent or unreadable."""
    try:
        value = _read(_path(root, agent)).get("sent_at")
    except (OSError, ValueError):
        return None
    return value if type(value) in (int, float) and math.isfinite(value) else None


def pending(root, agent):
    return _path(root, agent).exists()
