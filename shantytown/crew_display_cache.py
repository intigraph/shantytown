"""Display-only shared observation. No tracker or decision reader imports this."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import stat
import tempfile
import time

TTL = 15
MAX_BYTES = 1024 * 1024
RETRY_AFTER = 5


def boot_id():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def _regular(fd):
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077 or info.st_size > MAX_BYTES):
        raise ValueError('untrusted display cache file')


def directory():
    base = Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache')
    path = base / 'shantytown' / 'crew-display-v2'
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('untrusted display cache directory')
    return path


def _load(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd) as stream:
        _regular(stream.fileno())
        return json.load(stream)


def _publish(path, value):
    body = json.dumps(value).encode()
    if len(body) > MAX_BYTES:
        raise ValueError('display snapshot exceeds byte budget')
    fd, temporary = tempfile.mkstemp(prefix='.incoming-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(body)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


@contextmanager
def _lease(path):
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        _regular(fd)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def fresh(value, key, boot, now):
    return (isinstance(value, dict) and value.get('schema') == 2
            and value.get('key') == key and value.get('boot') == boot
            and type(value.get('started')) in (float, int)
            and type(value.get('finished')) in (float, int)
            and 0 <= now - value['started'] < TTL
            and value['started'] <= value['finished'] <= now
            and isinstance(value.get('payload'), dict))


def read(key, build, *, validate):
    """Single-flight refresh. Missing/expired/failed reads never fall back live.

    A complete failed attempt gets a five-second backoff. Contenders never wait
    on HTTP: a fresh observation is returned, otherwise they get UNKNOWN.
    """
    try:
        # Keys are canonical SHA256 digests, never filesystem paths. Refuse
        # before creating a directory or touching a lease/snapshot/backoff file.
        if (type(key) is not str or len(key) != 64
                or any(char not in "0123456789abcdef" for char in key)):
            raise ValueError("invalid display cache key")
        folder, boot = directory(), boot_id()
        path, failure = folder / (key + '.json'), folder / (key + '.failure')

        def hit():
            try:
                value = _load(path)
                if fresh(value, key, boot, time.monotonic()):
                    validate(value['payload'])
                    return value
            except (OSError, ValueError, TypeError, KeyError):
                pass
            return None

        if value := hit():
            return value
        with _lease(folder / (key + '.lock')):
            if value := hit():
                return value
            try:
                previous = _load(failure)
            except (OSError, ValueError, TypeError):
                previous = {}
            if (isinstance(previous, dict) and previous.get('boot') == boot
                    and type(previous.get('at')) in (float, int)
                    and 0 <= time.monotonic() - previous['at'] < RETRY_AFTER):
                raise ValueError('display refresh backoff')
            started = time.monotonic()
            try:
                payload = build()
                validate(payload)
                value = dict(schema=2, key=key, boot=boot, started=started,
                             finished=time.monotonic(), sampled_at=time.time(), payload=payload)
                if not fresh(value, key, boot, time.monotonic()):
                    raise ValueError('display refresh already expired')
                _publish(path, value)
                return value
            except Exception:
                _publish(failure, dict(boot=boot, at=time.monotonic()))
                raise
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
        # Diagnostics describe the class, never subprocess output/credentials.
        raise ValueError('display snapshot UNKNOWN: ' + type(error).__name__) from None
