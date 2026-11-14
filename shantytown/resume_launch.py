"""Observe ordinary administrator cold launches; never cause one.

The launch seam writes only after live-process, hooks and startup inbox checks.
This receipt resurfaces acceptance work, not proof of every governor scenario or
provider response. Recycles, overrides and dry-runs cannot produce it.
"""
from __future__ import annotations

import json
import os
import re
import socket
import stat
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

KIND = "cold-launch"
_ARG = re.compile(r"([a-z][a-z0-9_-]{0,63})(?:@(.+))?")
MAX_BYTES = 16384


def stamp(text):
    if (not isinstance(text, str)
            or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", text)):
        raise ValueError("cold-launch timestamp requires explicit UTC Z")
    value = datetime.fromisoformat(text[:-1] + "+00:00")
    if value.utcoffset().total_seconds() != 0:
        raise ValueError("cold-launch timestamp is not UTC")
    return value


def validate(arg):
    match = _ARG.fullmatch(arg)
    if not match:
        raise ValueError("use cold-launch:<agent> or cold-launch:<agent>@<UTC Z>")
    agent, since = match.groups()
    if since is not None:
        stamp(since)
    return agent, since


def _path(root, agent):
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", agent):
        raise ValueError("invalid launch identity")
    return Path(root).absolute() / "notify" / "resume-launches" / (agent + ".json")


def record(root, card, *, administrator, harness, session, cold, ordinary,
           live, hooks, inbox, now=None):
    """False means ineligible, never a launch request or an exemption."""
    if not all(v is True for v in (administrator, cold, ordinary, live, hooks, inbox)):
        return False
    from .harness import name_for
    if (not isinstance(harness, str) or not harness
            or harness != name_for(card, root=root)):
        return False
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or not isinstance(session, str) or not session:
        raise ValueError("launch receipt identity unavailable")
    path = _path(root, card.name)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.parent.lstat()
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_mode & 0o022 or info.st_uid not in (0, os.geteuid())):
        raise ValueError("untrusted launch receipt directory")
    body = dict(schema=1, root=str(Path(root).resolve()), agent=card.name,
                host=socket.gethostname(), harness=harness, administrator=True,
                kind="ordinary-cold-launch", session=session, id=str(uuid.uuid4()),
                at=now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                live=True, hooks=True, inbox=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as output:
        temporary = Path(output.name)
        try:
            json.dump(body, output)
            output.flush()
            os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return True


def _read(path):
    # Item text cannot select a path. Refuse links at every directory component
    # and nonregular/writable/oversized files, as the older event reader does.
    directory = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parts[1:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=directory)
            os.close(directory)
            directory = child
        info = os.fstat(directory)
        if info.st_mode & 0o022 or info.st_uid not in (0, os.geteuid()):
            raise ValueError("untrusted launch receipt directory")
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    finally:
        os.close(directory)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_mode & 0o022
                or before.st_uid not in (0, os.geteuid()) or before.st_size > MAX_BYTES):
            raise ValueError("untrusted launch receipt")
        raw = os.read(fd, MAX_BYTES + 1)
        after = os.fstat(fd)
        if (len(raw) != before.st_size or len(raw) > MAX_BYTES
                or (before.st_mtime_ns, before.st_ctime_ns, before.st_size)
                != (after.st_mtime_ns, after.st_ctime_ns, after.st_size)):
            raise ValueError("launch receipt changed during read")
        return raw
    finally:
        os.close(fd)


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate launch receipt field")
        value[key] = item
    return value


def evaluate(arg, root, now, *, row=None):
    try:
        agent, since = validate(arg)
        if since is None:
            from .resume_producers import _deferred_at
            boundary = datetime.fromtimestamp(_deferred_at(row or {}, now), timezone.utc)
        else:
            boundary = stamp(since)
        if root is None:
            return None, "launch receipt deployment root is unavailable"
        path = _path(root, agent)
        try:
            raw = _read(path)
        except FileNotFoundError:
            return False, "no qualifying launch receipt exists yet"
        data = json.loads(raw, object_pairs_hook=_unique)
        if (not isinstance(data, dict) or type(data.get("schema")) is not int
                or data["schema"] != 1 or data.get("root") != str(Path(root).resolve())
                or data.get("host") != socket.gethostname() or data.get("agent") != agent
                or data.get("kind") != "ordinary-cold-launch"
                or not isinstance(data.get("harness"), str) or not data["harness"]
                or not all(data.get(k) is True for k in ("administrator", "live", "hooks", "inbox"))
                or not isinstance(data.get("session"), str) or not data["session"]
                or not isinstance(data.get("id"), str) or not data["id"]):
            return None, "launch receipt identity or verification is unreadable"
        at = stamp(data.get("at"))
        if now.tzinfo is None or at > now or boundary > now:
            return None, "launch receipt clock is unreadable or in the future"
        met = at > boundary if since is None else at >= boundary
        return met, "verified ordinary administrator cold-launch receipt"
    except (OSError, ValueError, TypeError, AttributeError, RecursionError):
        return None, "launch receipt UNKNOWN; no lifecycle action attempted"
