"""Per-host 'quipu is busy' signal shared by every st process (aegis-jve).

WHY. Under read pressure every st process kept asking: each status segment,
hook and census re-read quipu on its own schedule and retried into the same
queue. A busy answer (408 / 429 / 503) told nothing to the next caller.

WHAT. A busy answer records `busy until <now + Retry-After>` for that server in
one private per-host file (Retry-After honoured, else 5 s; clamped to 1..30 s).
While it holds, BACKGROUND callers (`QUIPU_PRIORITY=background`, or an st
invocation in query_identity.BACKGROUND_INVOCATIONS: status segments,
dashboards, tend) do not touch the network; they fail fast with a
"quipu busy" error that the snapshot/UNKNOWN paths already treat as transient.
Normal callers are never blocked by this: they read as before, and their busy
answers refresh the signal. Storage failures only disable the gate.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import time

DEFAULT_SECONDS = 5
MAX_SECONDS = 30
BUSY_CODES = frozenset({408, 429, 503})


class QuipuBusy(TimeoutError):
    """A background read skipped because quipu recently said it was busy."""


def background() -> bool:
    from .query_identity import read_priority
    return read_priority() == "background"


def _path(server: str) -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    directory = base / "shantytown" / "quipu-busy-v1"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("untrusted quipu busy directory")
    key = hashlib.sha256(server.rstrip("/").encode()).hexdigest()[:32]
    return directory / f"{key}.json"


def retry_after_seconds(value) -> int:
    try:
        seconds = int(str(value).strip())
    except (TypeError, ValueError):
        seconds = DEFAULT_SECONDS
    return max(1, min(seconds, MAX_SECONDS))


def record(server: str, retry_after=None, *, now: float | None = None) -> None:
    """Note a busy answer; best effort, never raises."""
    try:
        until = (time.time() if now is None else now) + retry_after_seconds(retry_after)
        path = _path(server)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump({"until": until}, stream)
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
    except (OSError, ValueError):
        return


def remaining(server: str, *, now: float | None = None) -> float:
    """Seconds of recorded busyness left for this server; 0 when none or unreadable."""
    try:
        path = _path(server)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd) as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077 or info.st_size > 4096):
                return 0.0
            until = json.load(stream).get("until")
    except (OSError, ValueError, AttributeError):
        return 0.0
    if not isinstance(until, (int, float)):
        return 0.0
    left = until - (time.time() if now is None else now)
    return left if 0 < left <= MAX_SECONDS else 0.0


def gate(server: str) -> None:
    """Refuse a BACKGROUND read while quipu is recorded busy."""
    if background():
        left = remaining(server)
        if left > 0:
            raise QuipuBusy(f"quipu busy: background read skipped for {left:.0f}s more")


def observe(server: str, error: BaseException) -> None:
    """Record busyness from an HTTP error, if it is one of the busy codes."""
    code = getattr(error, "code", None)
    if code in BUSY_CODES:
        headers = getattr(error, "headers", None)
        record(server, headers.get("Retry-After") if headers is not None else None)
