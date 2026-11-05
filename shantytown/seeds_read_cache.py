"""Optional shared read acceleration, never a tracker or a stale-read fallback.

Hits share a one-second observation of (store_id, watermark_tx). Results are
published only when that pair stayed unchanged across a successful fetch.
Striped file locks protect local publication only; no HTTP runs under a lock.
Single reads retry a moving transaction at most three times. Owner projections
repair only changed entity fields and restart on membership/store changes,
keeping exact answers despite unrelated commits. Cache storage failure retains
a fenced uncached reader. Missing change-feed proof refuses the answer. A store
replacement discards retained rows before starting a new complete projection.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import time
from urllib.parse import urlencode, urlsplit
from urllib.request import Request

from .query_identity import read_headers

_LIMIT = 1024 * 1024
_ENTRIES = 64
_MAX_AGE = 60
_WATERMARK_MAX_AGE = 1
_CACHE_ERRORS = (OSError, ValueError, TypeError, AttributeError, KeyError)
_DIRECT_READS = ContextVar("seeds_direct_reads", default=False)
_READ_SNAPSHOT = ContextVar("seeds_read_snapshot", default=(False, None))
_PROJECTION = ContextVar("seeds_projection_fence", default=None)
_CHANGE_TX_LIMIT = 100
_CHANGE_PAGES = 8


@contextmanager
def projection_reads(budget=None):
    """Collect the oldest observation used by one exact owner projection."""
    token = _PROJECTION.set({"mark": None, "paths": set(), "epoch": None,
                              "refresh": False, "pending": [], "budget": budget})
    try:
        yield
    finally:
        _PROJECTION.reset(token)


def _projection_mark(mark):
    scope = _PROJECTION.get()
    if scope is None:
        return
    previous = scope["mark"]
    if previous is not None and previous[0] != mark[0]:
        _forget_projection(scope)
        raise StoreChanged("seeds store changed across projection")
    scope["mark"] = mark if previous is None else (mark[0], min(previous[1], mark[1]))


def certify_projection(server, graphs, entities, membership, timeout, opener):
    """Prove no relevant scoped changes since ANY query/cache observation.

    Page to a fixed post-projection watermark, not a moving live head. A full
    page is not absence evidence. Missing, malformed or oversized proof refuses.
    The source change log retains whole transactions, including retractions.
    """
    scope = _PROJECTION.get()
    if scope is None or scope["mark"] is None:
        return  # Explicit query-only admission (or an entirely injected reader).
    store, since = scope["mark"]
    end_store, target = _watermark(server, projection_timeout(timeout), opener)
    if end_store != store:
        _forget_projection(scope)
        raise StoreChanged("seeds store changed across projection")
    if target < since:
        raise ValueError("seeds watermark regressed across projection")
    if target == since:
        _publish_projection(scope, (store, target))
        return
    epoch = scope["epoch"]
    changed = set()
    membership_changed = False
    deadline = time.monotonic() + projection_timeout(timeout)
    for graph in graphs:
        cursor = since
        for _ in range(_CHANGE_PAGES):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError("projection change-feed time budget reached")
            headers = {"X-Quipu-Client": "seeds", **read_headers()}
            headers["X-Quipu-Operation"] = "cache-changes"
            request = Request(server.rstrip("/") + "/changes?" + urlencode(
                {"since": cursor, "graph": graph, "limit": _CHANGE_TX_LIMIT,
                 "capture": "new_values"}), headers=headers)
            with opener(request, timeout=remaining) as response:
                if response.status != 200:
                    raise ValueError("projection change feed unavailable")
                body = response.read(_LIMIT + 1)
                if len(body) > _LIMIT:
                    raise ValueError("projection change-feed byte budget reached")
                page = json.loads(body)
            if not isinstance(page, dict) or page.get("truncated", False) is not False:
                raise ValueError("truncated projection change feed")
            source = page.get("source")
            if not isinstance(source, dict) or source.get("store_id") != store:
                raise ValueError("seeds store changed across projection")
            this_epoch = source.get("log_epoch")
            if not isinstance(this_epoch, str) or not this_epoch or (epoch is not None and epoch != this_epoch):
                raise ValueError("projection change-feed history changed")
            epoch = this_epoch
            records, next_tx, watermark = page.get("records"), page.get("next_tx"), page.get("watermark_tx")
            if (type(page.get("since")) is not int or page["since"] != cursor
                    or page.get("capture") != "new_values"
                    or not isinstance(records, list) or len(records) > 10000
                    or type(next_tx) is not int or next_tx < cursor
                    or type(watermark) is not int or watermark < target):
                raise ValueError("invalid projection change-feed page")
            transactions = set()
            for record in records:
                if (not isinstance(record, dict) or type(record.get("tx")) is not int
                        or not cursor < record["tx"] <= next_tx
                        or record.get("graph") != graph
                        or not isinstance(record.get("entity"), str) or not record["entity"]
                        or not isinstance(record.get("attribute"), str) or not record["attribute"]
                        or record.get("op") not in ("assert", "retract", "tombstone")):
                    raise ValueError("invalid projection change record")
                transactions.add(record["tx"])
                if record["tx"] <= target:
                    membership_changed |= record["attribute"] in membership
                    if record["entity"] in entities:
                        changed.add(record["entity"])
            if (next_tx != (max(transactions) if transactions else cursor)
                    or len(transactions) > _CHANGE_TX_LIMIT):
                raise ValueError("invalid projection change-feed cursor")
            if next_tx >= target or len(transactions) < _CHANGE_TX_LIMIT:
                break
            cursor = next_tx
        else:
            raise ValueError("projection change-feed page budget reached")

    projection_timeout(timeout)
    scope["epoch"] = epoch
    if membership_changed or changed:
        _forget_projection(scope)
        if membership_changed:
            raise WatermarkMoved("seeds membership changed during projection")
        raise EntityChanges(changed, (store, target))

    _publish_projection(scope, (store, target))


def _forget_projection(scope):
    for path in scope["paths"]:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    scope["pending"].clear()


def _publish_projection(scope, mark):
    # Every consumed query is certified by the owner membership/selected-entity
    # proof. Publish only now; a refused projection must not cache its misses.
    for directory, path, mark_path, result in scope["pending"]:
        try:
            with _locked(directory, path.stem[5:]):
                _publish(directory, mark_path, None, mark)
                _publish(directory, path, mark, result)
        except _CACHE_ERRORS:
            pass  # A correct answer does not depend on writable cache storage.
    scope["pending"].clear()


def projection_timeout(timeout):
    """One allowance shared by full restarts and entity repairs.

    timeout remains a per-request cap, not a one-second caller wall promise.
    The complete projection may use at most three such time allowances.
    """
    scope = _PROJECTION.get()
    budget = scope.get("budget") if scope is not None else None
    if budget is None:
        return timeout
    remaining = budget["deadline"] - time.monotonic()
    if remaining <= 0:
        raise ValueError("owner projection total time budget reached")
    return min(timeout, remaining)


def repair_entities(change):
    scope = _PROJECTION.get()
    budget = scope["budget"]
    if budget["remaining"] <= 0:
        raise ValueError("owner projection three-pass budget reached")
    projection_timeout(1)
    budget["remaining"] -= 1
    # Unchanged entities have been certified through this target. A repair
    # must read fresh fields, never an older shared cache entry. Re-fencing
    # all selected entities catches a second write during the repair itself.
    scope["mark"] = change.mark
    scope["refresh"] = True
    scope["paths"].clear()


@contextmanager
def direct_reads():
    """Keep bounded readers on their admitted query-only transport.

    Cache watermark requests are additional reads. A query-only consumer must
    opt out of acceleration rather than quietly widening its transport budget.
    Context-local state leaves concurrent ordinary readers unchanged.
    """
    token = _DIRECT_READS.set(True)
    try:
        yield
    finally:
        _DIRECT_READS.reset(token)


class WatermarkMoved(ValueError):
    """A changed observation; owner membership changes require full restart."""


class StoreChanged(WatermarkMoved):
    """The backing store changed; no retained rows may cross the restart."""


class EntityChanges(WatermarkMoved):
    """Payload-only changes whose selected fields can be repaired."""

    def __init__(self, entities, mark):
        super().__init__("selected entity payload changed during projection")
        self.entities = frozenset(entities)
        self.mark = mark


@contextmanager
def consistent_reads():
    """Fence a multi-query projection to one observed store/watermark pair."""
    token = _READ_SNAPSHOT.set((True, None))
    try:
        yield
    finally:
        _READ_SNAPSHOT.reset(token)


def _observe(mark):
    active, expected = _READ_SNAPSHOT.get()
    if active:
        if mark is None:
            raise ValueError("seeds watermark unavailable across projection")
        if expected is not None and mark != expected:
            if mark[0] != expected[0]:
                raise ValueError("seeds store changed across projection")
            raise WatermarkMoved("seeds watermark changed across projection; refusing mixed snapshot")
        _READ_SNAPSHOT.set((True, mark))


def primary_reads_required() -> bool:
    """Explicit query-only admission remains on its original transport."""
    return _DIRECT_READS.get()


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


def _cached(path: Path, watermark, validate, *, max_age=_MAX_AGE):
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
                or value.get("watermark") != (list(watermark) if watermark is not None else None)
                or not 0 <= age < max_age):
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
    entries = sorted(directory.glob(path.name[:5] + "*.json"), key=lambda p: p.stat().st_mtime)
    for old in entries[:-_ENTRIES]:
        old.unlink(missing_ok=True)


def read(server: str, query: str, timeout: int, *, opener, fetch, validate):
    # A projection owns its retry boundary: never keep its earlier fields and
    # retry just one query against a newer snapshot.
    scope = _PROJECTION.get()
    if scope is not None and not _DIRECT_READS.get() and scope["mark"] is None:
        _projection_mark(_watermark(server, timeout, opener))
    attempts = 1 if _READ_SNAPSHOT.get()[0] or scope is not None else 3
    for attempt in range(attempts):
        try:
            return _read_once(server, query, timeout, opener=opener,
                              fetch=fetch, validate=validate)
        except WatermarkMoved:
            if attempt == attempts - 1:
                raise


def _read_once(server: str, query: str, timeout: int, *, opener, fetch, validate):
    """Return a validated current read; errors never authorize cached fallback.

    The cache contains only bounded successful wire projections. The complete
    query (including graph/owner constants) is part of the key, so owners and
    boards never share answers. Hits share watermark metadata for at most one
    second. Misses still check both sides of the fetch, including a fresh
    post-fetch observation; an intervening write prevents publication.
    ST_SEEDS_READ_CACHE=0 disables acceleration for rollback/measurement.
    """
    scope = _PROJECTION.get()
    if scope is not None and scope["refresh"]:
        return fetch()
    parsed = urlsplit(server)
    if (_DIRECT_READS.get() or os.environ.get("ST_SEEDS_READ_CACHE") == "0"
            or parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        return fetch()
    key = hashlib.sha256(json.dumps([server, query]).encode()).hexdigest()
    try:
        directory = _directory()
        mark_key = hashlib.sha256(json.dumps([server, "watermark-v1"]).encode()).hexdigest()
        mark_path = directory / ("mark-" + mark_key + ".json")
        path = directory / ("read-" + key + ".json")

        def valid_mark(value):
            if (not isinstance(value, list) or len(value) != 2
                    or not isinstance(value[0], str) or not value[0]
                    or len(value[0]) > 256 or type(value[1]) is not int or value[1] < 0):
                raise ValueError("invalid cached watermark")
            return tuple(value)

        # The lock protects local files only. A slow reader must not hold a
        # cache stripe across HTTP and force unrelated readers to wait a second.
        with _locked(directory, key):
            before = _cached(mark_path, None, valid_mark, max_age=_WATERMARK_MAX_AGE)
            hit = _cached(path, before, validate) if before is not None else None
        if before is None:
            before = (scope["mark"] if scope is not None else
                      _watermark(server, timeout, opener))
            with _locked(directory, key):
                _publish(directory, mark_path, None, before)
                hit = _cached(path, before, validate)
    except _CACHE_ERRORS:
        if _PROJECTION.get() is not None:
            return fetch()  # The outer scope certifies this uncached query.
        if not _READ_SNAPSHOT.get()[0]:
            return fetch()
        # Unwritable cache files are not missing consistency evidence. Keep
        # the direct wire reader, with the same before/after watermark fence.
        before = _watermark(server, timeout, opener)
        _observe(before)
        result = fetch()
        after = _watermark(server, timeout, opener)
        if after[0] != before[0]:
            raise (StoreChanged if _PROJECTION.get() is not None else ValueError)(
                "seeds store changed during read")
        if after != before:
            raise WatermarkMoved("seeds watermark moved during read; refusing mixed snapshot")
        return result
    _observe(before)
    scope = _PROJECTION.get()
    if scope is not None:
        scope["paths"].update((path, mark_path))
    if hit is not None:
        _projection_mark(before)
        return hit

    if scope is not None:
        _projection_mark(before)
        result = fetch()
        scope["pending"].append((directory, path, mark_path, result))
        return result  # The whole projection owns the post-read proof.

    result = fetch()  # Never swallow a wire or completeness refusal.
    # A changed watermark cannot certify this answer, even without caching:
    # callers combine projections, so returning it could serve a mixed view.
    after = _watermark(server, timeout, opener)
    try:
        with _locked(directory, key):
            _publish(directory, mark_path, None, after)
            if after == before:
                _publish(directory, path, after, result)
    except _CACHE_ERRORS:
        pass  # A certified wire answer does not depend on writable cache files.
    if after[0] != before[0]:
        raise (StoreChanged if _PROJECTION.get() is not None else ValueError)(
                "seeds store changed during read")
    _projection_mark(after)
    if after != before and _PROJECTION.get() is None:
        raise WatermarkMoved("seeds watermark moved during read; refusing mixed snapshot")
    return result
