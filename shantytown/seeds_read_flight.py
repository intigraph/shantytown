"""Bound concurrent bounded-staleness misses, separate from publication locks.

64 stripes bound local files. Hash collisions may wait, but never hold a cache
publication lock across HTTP. A waiter times out rather than duplicating a slow
fetch. Exact readers never enter this seam.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
import stat
import time


@contextmanager
def flight(directory, parts, timeout):
    seconds = float(timeout)
    if not math.isfinite(seconds):
        raise ValueError("invalid shared read flight timeout")
    key = hashlib.sha256(json.dumps(parts).encode()).hexdigest()
    path = directory / f"flight-{int(key[:2], 16) % 64:02d}"
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("invalid shared read flight")
        deadline = time.monotonic() + min(max(seconds, 0), 5)
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("shared stale read still in flight")
                time.sleep(.01)
        yield fd
    finally:
        os.close(fd)


class SharedReadFailed(RuntimeError):
    """A shared stale fetch failed; this is a refusal, never cached success."""


def coalesce(directory, parts, timeout, *, lookup, fetch):
    started = time.monotonic()
    key = hashlib.sha256(json.dumps(parts).encode()).hexdigest()
    with flight(directory, parts, timeout) as fd:
        # Keep failures in the locked stripe so processes share the outcome.
        # Only hashes/times persist: never exception text, query text or secrets.
        os.lseek(fd, 0, os.SEEK_SET)
        raw = os.read(fd, 16385)
        failures = json.loads(raw) if raw else {}
        now = time.monotonic()
        if (not isinstance(failures, dict) or len(failures) > 64 or len(raw) > 16384
                or any(not isinstance(k, str) or not isinstance(v, (int, float))
                       or not math.isfinite(v) for k, v in failures.items())):
            raise ValueError("invalid shared read failure state")
        failures = {k: v for k, v in failures.items() if 0 <= now - v < 60}
        failed = failures.get(key)
        if failed is not None and (failed >= started or now - failed < 1):
            raise SharedReadFailed("shared stale fetch failed; retry after backoff")
        # A stripe collision must not evict a live cohort's failure outcome.
        if key not in failures and len(failures) >= 64:
            raise SharedReadFailed("shared stale failure budget full")
        hit, publish = lookup()
        if hit is not None:
            return hit
        try:
            result = fetch()
        except Exception:
            failures[key] = time.monotonic()
            body = json.dumps(failures).encode()
            os.lseek(fd, 0, os.SEEK_SET)
            remaining = memoryview(body)
            while remaining:
                remaining = remaining[os.write(fd, remaining):]
            os.ftruncate(fd, len(body))
            raise
        if publish is not None:
            publish(result)
        return result
