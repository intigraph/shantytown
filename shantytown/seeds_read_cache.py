"""Optional shared read acceleration, never a tracker or a stale-read fallback.

Every hit observes the server's current (store_id, watermark_tx). Results are
published only when that pair stayed unchanged across a successful fetch.
Striped file locks make identical concurrent readers share one fetch without
serializing all owners. Cache/metadata failures fall back to the original read.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import Request

from .query_identity import read_headers

_LIMIT = 1024 * 1024
_ENTRIES = 64
_MAX_AGE = 60
_CACHE_ERRORS = (OSError, ValueError, TypeError, AttributeError, KeyError)


def _directory() -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    directory = base / "shantytown" / "seeds-reads-v1"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("shared read cache is not private")
    return directory


@contextmanager
def _locked(directory: Path, key: str):
    path = directory / f"lock-{int(key[:2], 16) % 64:02d}"
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("invalid shared read lock")
        deadline = time.monotonic() + 1
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("shared read lock busy")
                time.sleep(0.01)
        yield
    finally:
        os.close(fd)


def _watermark(server: str, timeout: int, opener) -> tuple[str, int]:
    headers = {"X-Quipu-Client": "seeds", **read_headers()}
    headers["X-Quipu-Operation"] = "cache-watermark"
    request = Request(server.rstrip("/") + "/watermark", headers=headers)
    with opener(request, timeout=min(timeout, 2)) as response:
        if response.status != 200:
            raise ValueError("watermark unavailable")
        body = response.read(4097)
        if len(body) > 4096:
            raise ValueError("watermark byte budget exceeded")
        value = json.loads(body)
    if (not isinstance(value, dict) or not isinstance(value.get("store_id"), str)
            or not value["store_id"] or len(value["store_id"]) > 256
            or type(value.get("watermark_tx")) is not int or value["watermark_tx"] < 0):
        raise ValueError("invalid watermark")
    return value["store_id"], value["watermark_tx"]


def _cached(path: Path, watermark, validate):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077 or info.st_size > _LIMIT):
                return None
            value = json.load(stream)
        age = time.time() - value["created"]
        if (value.get("schema") != 1 or value.get("key") != path.stem[5:]
                or value.get("watermark") != list(watermark)
                or not 0 <= age < _MAX_AGE):
            return None
        return validate(value["result"])
    except _CACHE_ERRORS:
        return None


def _publish(directory: Path, path: Path, watermark, result):
    body = json.dumps({"schema": 1, "key": path.stem[5:], "watermark": watermark,
                       "created": time.time(), "result": result}).encode()
    if len(body) > _LIMIT:
        return
    fd, temporary = tempfile.mkstemp(prefix="incoming-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(body)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    entries = sorted(directory.glob("read-*.json"), key=lambda p: p.stat().st_mtime)
    for old in entries[:-_ENTRIES]:
        old.unlink(missing_ok=True)


def read(server: str, query: str, timeout: int, *, opener, fetch, validate):
    """Return a validated current read; errors never authorize cached fallback.

    The cache contains only bounded successful wire projections. The complete
    query (including graph/owner constants) is part of the key, so owners and
    boards never share answers. A fresh server watermark is required on hits.
    ST_SEEDS_READ_CACHE=0 disables acceleration for rollback/measurement.
    """
    parsed = urlsplit(server)
    if (os.environ.get("ST_SEEDS_READ_CACHE") == "0"
            or parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        return fetch()
    key = hashlib.sha256(json.dumps([server, query]).encode()).hexdigest()
    try:
        directory = _directory()
        lock = _locked(directory, key)
        lock.__enter__()
    except _CACHE_ERRORS:
        return fetch()
    try:
        try:
            before = _watermark(server, timeout, opener)
            path = directory / ("read-" + key + ".json")
            hit = _cached(path, before, validate)
        except _CACHE_ERRORS:
            return fetch()
        if hit is not None:
            return hit
        result = fetch()  # Deliberately outside the cache-error handler.
        try:
            after = _watermark(server, timeout, opener)
            if after == before:
                _publish(directory, path, after, result)
        except _CACHE_ERRORS:
            pass
        return result
    finally:
        lock.__exit__(None, None, None)
