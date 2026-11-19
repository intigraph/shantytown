"""Last complete owner-capacity observation, used ONLY while quipu is busy (aegis-jve).

WHY. `plate_capacity.counted_rows` turned every failed owner-row read, including
a quipu 408 under read pressure, into "plate size UNKNOWN", and assignment
admission then refused. On 2026-11-19 that refused three dispatches in a row
while the store was merely queue-bound.

WHAT. Every COMPLETE owner-capacity read publishes its rows here, one private
file per (store identity, owner). When a later read fails with a TRANSIENT busy
signal (408 / 429 / 503 / timeout) and this host holds a snapshot of the same
owner on the same store that is at most MAX_AGE seconds old, the caller may
count from it and must say so. Anything else (a partial or truncated read, an
older snapshot, a different store, a malformed file) stays UNKNOWN exactly as
before. This is a bounded, labelled exception to the no-fallback rule, not a
cache for normal reads: a successful read always uses the live answer.

Residual risk, accepted for <= MAX_AGE seconds: an assignment made from the
snapshot can exceed the cap by the assignments made since it was taken; the
next complete read sees the true count.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time

MAX_AGE = 60
MAX_BYTES = 1024 * 1024
_SCHEMA = 1

# A transient "server busy" signal from the read path, as it surfaces in the
# PartialAnswer caveat / exception text. Deliberately narrow: truncation,
# shape refusals and unknown errors do NOT match and keep refusing.
# Status codes count only in an HTTP context ("HTTP Error 408", "status 503",
# "code=429"), so an identifier such as aegis-503 never reads as busy.
_TRANSIENT = re.compile(
    r"\b(?:http(?: error)?|status|code)\s*[:=]?\s*(?:408|429|503)\b"
    r"|request timeout|too many requests|service unavailable"
    r"|timed out|read timeout|quipu busy",
    re.IGNORECASE,
)


def transient(error: BaseException | str) -> bool:
    return bool(_TRANSIENT.search(str(error)))


def identity(tracker) -> tuple | None:
    """Store identity for a Seeds tracker; None (no snapshot) for any other."""
    prove = getattr(tracker, "prove_store", None)
    if not callable(prove):
        return None
    try:
        proof = prove()
    except Exception:  # noqa: BLE001 - no proof, no snapshot
        return None
    url, graph = getattr(proof, "quipu_url", None), getattr(proof, "graph", None)
    if not url or not graph:
        return None
    return (url, graph, getattr(proof, "prefix", None))


def _directory() -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    path = base / "shantytown" / "owner-capacity-v1"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("untrusted owner snapshot directory")
    return path


def _path(ident: tuple, owner: str) -> Path:
    key = hashlib.sha256(json.dumps([list(ident), owner]).encode()).hexdigest()
    return _directory() / f"{key}.json"


def publish(ident: tuple | None, owner: str, rows: list) -> None:
    """Record a COMPLETE read. Best effort: a storage failure never fails the read."""
    if ident is None:
        return
    try:
        body = json.dumps({"schema": _SCHEMA, "at": time.time(), "identity": list(ident),
                           "owner": owner, "rows": rows}, default=str).encode()
        if len(body) > MAX_BYTES:
            return
        target = _path(ident, owner)
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(body)
            os.chmod(tmp, 0o600)
            os.replace(tmp, target)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
    except (OSError, ValueError, TypeError):
        return


def fresh(ident: tuple | None, owner: str, *, now: float | None = None) -> tuple[list, float] | None:
    """The same owner's rows on the same store, at most MAX_AGE old, else None."""
    if ident is None:
        return None
    try:
        path = _path(ident, owner)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077 or info.st_size > MAX_BYTES):
                return None
            data = json.loads(stream.read())
    except (OSError, ValueError):
        return None
    if (not isinstance(data, dict) or data.get("schema") != _SCHEMA
            or data.get("identity") != list(ident) or data.get("owner") != owner
            or not isinstance(data.get("rows"), list)
            or not all(isinstance(row, dict) for row in data["rows"])
            or not isinstance(data.get("at"), (int, float))):
        return None
    age = (time.time() if now is None else now) - data["at"]
    if not 0 <= age <= MAX_AGE:
        return None
    return data["rows"], age
