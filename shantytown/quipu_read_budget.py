"""Opt-in host-local admission for initial Python Quipu HTTP read dispatches.

This is a cooperative resource cap, not authorization. No network work runs
under the ledger lock. Failed attempts retain their admission charge. SDK child
traffic and automatic transport redirects are outside this counter's coverage.
"""
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import time
from urllib.parse import urlsplit


class ReadBudgetRefused(ValueError):
    """No read was dispatched; this is neither an empty result nor server health."""


def admit(server):
    raw = os.environ.get('ST_QUIPU_READS_PER_MINUTE', '0').strip()
    try:
        limit = int(raw)
        if not 0 <= limit <= 10000:
            raise ValueError()
    except ValueError:
        raise ReadBudgetRefused('invalid local Quipu read budget') from None
    if limit == 0:
        return False
    try:
        parsed = urlsplit(server)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError()
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        origin = [parsed.scheme, parsed.hostname.lower(), port]
        key = hashlib.sha256(json.dumps(origin).encode()).hexdigest()
        directory = Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache') / 'shantytown' / 'read-budget-v1'
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError()
        fd = os.open(directory / (key + '.json'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError()
            deadline = time.monotonic() + .1
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise ReadBudgetRefused('local Quipu read budget ledger busy')
                    time.sleep(.005)
            raw = os.read(fd, 256001)
            times = json.loads(raw) if raw else []
            now = time.time()
            if (len(raw) > 256000 or not isinstance(times, list) or len(times) > 10000
                    or not math.isfinite(now) or any(type(t) not in (int, float)
                    or not math.isfinite(t) or t < 0 or t > now for t in times)
                    or times != sorted(times)):
                raise ValueError()
            times = [t for t in times if now - t < 60]
            if len(times) >= limit:
                seconds = max(1, math.ceil(times[0] + 60 - now))
                raise ReadBudgetRefused(f'local Quipu read budget exhausted; retry after {seconds}s')
            times.append(now)
            body = json.dumps(times).encode()
            os.lseek(fd, 0, os.SEEK_SET)
            remaining = memoryview(body)
            while remaining:
                remaining = remaining[os.write(fd, remaining):]
            os.ftruncate(fd, len(body))
        finally:
            os.close(fd)
        return True
    except ReadBudgetRefused:
        raise
    except (OSError, ValueError, TypeError):
        raise ReadBudgetRefused('local Quipu read budget ledger unavailable; no read dispatched') from None
