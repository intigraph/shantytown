"""Short-lived cache for `st inbox --count`, the status-bar poll (aegis-dnw).

Every tmux status line runs `shanty seg inbox` each 60 s, which runs
`st inbox --count <agent>`. Measured 2026-11-21 22:25-22:55Z: that command made
~509 of the fleet's 2802 seeds /query reads in 30 minutes (one /health, /graphs
and /stats plus 4-5 queries per call). The answer changes only when mail
arrives or is acknowledged, so the count is cached per agent for a short TTL
and dropped by every change this host makes to that inbox: a durable send to
the agent, or the agent's own ack or disposition.

Bounds, stated plainly: mail sent from ANOTHER host is seen after at most the
TTL. Only the CLI `--count` answer is cached; listing, acking and every
internal reader still read the store. A missing, unreadable, foreign or
future-dated entry is a miss, never a count. ST_INBOX_COUNT_TTL=0 disables the
cache (the rollback).
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

DEFAULT_TTL = 180


def ttl() -> int:
    raw = os.environ.get("ST_INBOX_COUNT_TTL", "").strip()
    if not raw:
        return DEFAULT_TTL
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_TTL


def _dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "shantytown" / "inbox-count"


def _path(agent: str) -> Path:
    return _dir() / (hashlib.sha256(agent.encode()).hexdigest()[:32] + ".json")


def get(agent: str, now: float | None = None) -> int | None:
    limit = ttl()
    if not limit or not agent:
        return None
    now = time.time() if now is None else now
    try:
        row = json.loads(_path(agent).read_text())
    except (OSError, ValueError):
        return None
    at, count = row.get("at"), row.get("count")
    if (row.get("agent") != agent or type(count) is not int or count < 0
            or not isinstance(at, (int, float)) or not 0 <= now - at < limit):
        return None
    return count


def put(agent: str, count: int, now: float | None = None) -> None:
    if not ttl() or not agent or type(count) is not int or count < 0:
        return
    path = _path(agent)
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}")
        tmp.write_text(json.dumps({"agent": agent, "count": count,
                                   "at": time.time() if now is None else now}))
        os.replace(tmp, path)
    except OSError:
        pass  # A cache that cannot be written is only a slower status bar.


def invalidate(*agents) -> None:
    """Drop the cached count for each agent (a name or an Agent card); never raises."""
    for agent in agents:
        agent = getattr(agent, "name", agent)
        if not isinstance(agent, str) or not agent:
            continue
        for name in {agent, agent.split("/")[-1]}:
            try:
                _path(name).unlink()
            except OSError:
                pass
