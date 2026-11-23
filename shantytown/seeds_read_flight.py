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
        yield
    finally:
        os.close(fd)


def coalesce(directory, parts, timeout, *, lookup, fetch):
    with flight(directory, parts, timeout):
        # Another process may have completed while we waited. Re-observe the
        # write generation too; never publish under a pre-wait generation.
        hit, publish = lookup()
        if hit is not None:
            return hit
        result = fetch()
        if publish is not None:
            publish(result)
        return result
