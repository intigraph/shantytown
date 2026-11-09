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


def snapshot(root, agent):
    """The exact agent's hook-fed identity; not a newest-file guess."""
    _path(root, agent)  # validate before composing any path
    row = _read(Path(root) / "context_budget" / f"{agent}.json")
    identity, at = row.get("payload"), row.get("at")
    if (not isinstance(identity, dict) or type(at) not in (int, float)
            or not math.isfinite(at) or not 0 <= time.time() - at <= 1800):
        raise ValueError("no fresh hook session identity")
    if any(not isinstance(identity.get(k), str) or not identity[k]
           for k in ("session_id", "transcript_path")):
        raise ValueError("incomplete hook session identity")
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


def pending(root, agent):
    return _path(root, agent).exists()
