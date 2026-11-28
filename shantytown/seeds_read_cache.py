"""Optional shared read acceleration, never a tracker or a stale-read fallback.

Ordinary hits share a one-second observation of (store_id, watermark_tx).
Projection scopes take one fresh initial observation and certify all consumed
rows through a post-query change-feed target; they never share that initial
observation across scopes. Ordinary results publish only when the pair stayed
unchanged across a successful fetch.
Striped publication locks protect local files only. Bounded-staleness misses
share a separate bounded flight lock; exact readers never enter that seam.
Single reads retry a moving transaction at most three times. Owner projections
repair only changed entity fields and restart on membership/store changes,
keeping exact answers despite unrelated commits. Exact-cache storage failure
retains a fenced uncached reader; unavailable display flights refuse the miss.
Missing change-feed proof refuses the answer. A store
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
from urllib.error import HTTPError, URLError

from .query_identity import read_headers
from . import quipu_busy
from .quipu_read_budget import open_read, ReadBudgetRefused

_LIMIT = 1024 * 1024
_ENTRIES = 64
_MAX_AGE = 60
_WATERMARK_MAX_AGE = 1
_CACHE_ERRORS = (OSError, ValueError, TypeError, AttributeError, KeyError)
_DIRECT_READS = ContextVar("seeds_direct_reads", default=False)
_READ_SNAPSHOT = ContextVar("seeds_read_snapshot", default=(False, None))
_PROJECTION = ContextVar("seeds_projection_fence", default=None)
_RETAIN_CANDIDATES = ContextVar("seeds_retain_candidates", default=False)
_CHANGE_TX_LIMIT = 100
_CHANGE_PAGES = 8
# aegis-jve J3: bounded-staleness tier for per-turn crew reads (stop hooks,
# inbox, sd list/ready). Never above _MAX_AGE; 0 disables.
_DEFAULT_STALE_TTL = 60.0
_STALE_TTL = ContextVar("seeds_stale_ttl", default=0.0)
# aegis-dnw: an explicit, wider ceiling one caller may ask for (the
# administrator stop hook). Never above _EXTENDED_MAX_AGE; own writes still
# invalidate, and ST_SEEDS_STALE_TTL=0 still turns the whole tier off.
_EXTENDED_MAX_AGE = 300.0
_STALE_CAP = ContextVar("seeds_stale_cap", default=None)
_GENERATION = "ttl-generation"
_OWNER_GENERATION = "owner-display-generation"


def stale_ttl() -> float:
    """ST_SEEDS_STALE_TTL seconds (default 60, capped at 60; 0 disables)."""
    raw = os.environ.get("ST_SEEDS_STALE_TTL")
    if raw is None:
        return _DEFAULT_STALE_TTL
    try:
        value = float(raw)
    except ValueError:
        return 0.0
    return max(0.0, min(value, float(_MAX_AGE)))


def _cap() -> float:
    """The ceiling for this scope: stale_ttl(), or the explicit wider ttl."""
    cap = _STALE_CAP.get()
    return stale_ttl() if cap is None else (cap if stale_ttl() > 0 else 0.0)


@contextmanager
def stale_ok(ttl=None):
    """Admit answers up to stale_ttl() old (or an explicit ttl, at most
    _EXTENDED_MAX_AGE) inside this block.

    For per-turn reads whose callers already tolerate a moving board (a stop
    hook, an inbox view, a plate listing). Work-board and uncertain writes
    invalidate all older answers. Successful native message-window writes
    preserve only complete owner displays, whose board has not changed.
    A fetch overlapping an affecting write is never published. Exact readers (projections,
    snapshots, direct/primary reads) never see this tier.
    """
    value, cap = stale_ttl(), None
    if ttl is not None and value > 0:
        value = cap = max(0.0, min(float(ttl), _EXTENDED_MAX_AGE))
    token, cap_token = _STALE_TTL.set(value), _STALE_CAP.set(cap)
    try:
        yield
    finally:
        _STALE_CAP.reset(cap_token)
        _STALE_TTL.reset(token)


@contextmanager
def exact_reads():
    """Refuse the bounded-staleness tier inside this block, even under stale_ok().

    aegis-jve: a read that proves something before a write (a claim's
    readiness, a release gate) must take the exact fence however its caller
    was entered.
    """
    token = _STALE_TTL.set(0.0)
    try:
        yield
    finally:
        _STALE_TTL.reset(token)


def _generation(directory: Path, name=_GENERATION) -> int:
    path = directory / name
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return 0
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("stale-read generation is not private")
        value = int(stream.read(64).decode() or 0)
    if value < 0:
        raise ValueError("invalid stale-read generation")
    return value


def invalidate_stale(*, message_only=False) -> None:
    """Invalidate stale reads; message-only writes preserve board owner displays.

    Bumps the affected bounded-staleness generations and drops shared watermark
    observations, so the next exact read must observe the post-write
    watermark and cannot republish a pre-write answer. If the generation
    cannot be written, every bounded-staleness entry is removed instead;
    lookups also refuse the tier while the cache cannot be written, so the
    fail-closed state survives this process.
    """
    scope = _PROJECTION.get()
    while scope is not None:
        scope["failure"] = ValueError("projection invalidated by a write; start a new scope")
        _forget_projection(scope)
        scope = scope["parent"]
    try:
        directory = _directory()
    except _CACHE_ERRORS:
        return  # no cache directory: nothing can be served from it either
    for mark in directory.glob("mark-*.json"):
        try:
            mark.unlink(missing_ok=True)
        except OSError:
            pass
    try:
        # Native message windows are outside the work board. Only a known
        # successful window mutation may preserve a bounded owner display;
        # every ordinary/uncertain write still invalidates both generations.
        names = (_GENERATION,) if message_only else (_GENERATION, _OWNER_GENERATION)
        for name in names:
            fd, temporary = tempfile.mkstemp(prefix="incoming-", dir=directory)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(str(time.time_ns()).encode())
                os.replace(temporary, directory / name)
            finally:
                Path(temporary).unlink(missing_ok=True)
    except _CACHE_ERRORS:
        for entry in directory.glob("ttlr-*.json"):
            try:
                entry.unlink(missing_ok=True)
            except OSError:
                pass


def _stale_fence_age() -> float:
    """Seconds a stale_ok() read may reuse an observed watermark; 0 when exact.

    aegis-jve: a stale-tier caller already accepts answers up to the stale TTL,
    so paying the exact 1s /watermark fence on its misses buys no consistency.
    Projections, snapshots and direct reads stay exact; own writes drop the
    marks (invalidate_stale), so the next read observes again.
    """
    ttl = _STALE_TTL.get()
    if (ttl <= 0 or _DIRECT_READS.get() or _PROJECTION.get() is not None
            or _READ_SNAPSHOT.get()[0] or os.environ.get("ST_SEEDS_READ_CACHE") == "0"):
        return 0.0
    return min(ttl, _cap())


def stale_lookup(parts, validate, *, ttl=None, owner_display=False):
    """(hit, publish) for one bounded-staleness key; (None, None) when off.

    `publish(result)` stores a fresh answer only if no write bumped the
    generation since this lookup.
    """
    ttl = _STALE_TTL.get() if ttl is None else ttl
    if (ttl <= 0 or _DIRECT_READS.get() or _PROJECTION.get() is not None
            or _READ_SNAPSHOT.get()[0] or os.environ.get("ST_SEEDS_READ_CACHE") == "0"
            or stale_ttl() <= 0):
        return None, None
    key = hashlib.sha256(json.dumps(["stale-v1", *parts]).encode()).hexdigest()
    name = _OWNER_GENERATION if owner_display else _GENERATION

    def current_generation(directory):
        return (_generation(directory, name) if owner_display else _generation(directory))

    try:
        directory = _directory()
        if not os.access(directory, os.W_OK):
            return None, None  # an invalidation could not land: tier off
        path = directory / ("ttlr-" + key + ".json")
        with _locked(directory, key):
            generation = [name, current_generation(directory)]
            hit = _cached(path, generation, validate, max_age=min(ttl, _cap()))
    except _CACHE_ERRORS:
        return None, None
    if hit is not None:
        return hit, None

    def publish(result):
        try:
            with _locked(directory, key):
                if current_generation(directory) == generation[1]:
                    _publish(directory, path, generation, result)
        except _CACHE_ERRORS:
            pass

    return None, publish


@contextmanager
def projection_reads(budget=None):
    """Collect the oldest observation used by one exact owner projection."""
    token = _PROJECTION.set({"mark": None, "paths": set(), "epoch": None,
                              "refresh": False, "pending": [], "budget": budget,
                              "watermark": None, "server": None, "failure": None,
                              "parent": _PROJECTION.get()})
    try:
        yield
    finally:
        _PROJECTION.reset(token)


@contextmanager
def candidate_reads():
    """Reuse candidate observations only inside a complete projection fence.

    The retained transaction is certified by the existing membership/change
    proof before any answer escapes; this never permits stale field reads.
    """
    token = _RETAIN_CANDIDATES.set(True)
    try:
        yield
    finally:
        _RETAIN_CANDIDATES.reset(token)


def store_admission_required():
    """Consume a replacement-store admission requirement within this read."""
    scope = _PROJECTION.get()
    budget = scope.get("budget") if scope is not None else None
    return bool(budget is not None and budget.pop("store_changed", False))


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
    scope = _projection_check(server)
    if scope is None or scope["mark"] is None:
        return  # Explicit query-only admission (or an entirely injected reader).
    store, since = scope["mark"]
    # A reused initial mark cannot certify queries made after it. The first
    # post-query change page supplies a fresh fixed target instead of paying
    # for a second /watermark. Every graph/page still proves through that target.
    target = None
    epoch = scope["epoch"]
    changed = set()
    membership_changed = set()
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
            with open_read(server, request, timeout=remaining, opener=opener) as response:
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
                _forget_projection(scope)
                raise StoreChanged("seeds store changed across projection")
            this_epoch = source.get("log_epoch")
            if not isinstance(this_epoch, str) or not this_epoch or (epoch is not None and epoch != this_epoch):
                raise ValueError("projection change-feed history changed")
            epoch = this_epoch
            records, next_tx, watermark = page.get("records"), page.get("next_tx"), page.get("watermark_tx")
            if (type(page.get("since")) is not int or page["since"] != cursor
                    or page.get("capture") != "new_values"
                    or not isinstance(records, list) or len(records) > 10000
                    or type(next_tx) is not int or next_tx < cursor
                    or type(watermark) is not int or watermark < since or next_tx > watermark
                    or (target is not None and watermark < target)):
                raise ValueError("invalid projection change-feed page")
            if target is None:
                target = watermark
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
                    if record["attribute"] in membership:
                        membership_changed.add(record["entity"])
                    if record["entity"] in entities:
                        changed.add(record["entity"])
            if (next_tx != (max(transactions) if transactions else cursor)
                    or len(transactions) > _CHANGE_TX_LIMIT):
                raise ValueError("invalid projection change-feed cursor")
            if target == since:
                # The page's global head proves no commits in ANY graph since
                # the oldest consumed row. No second graph/page is necessary.
                _projection_check(server)
                projection_timeout(timeout)
                scope["epoch"] = epoch
                _publish_projection(scope, (store, target))
                return
            if next_tx >= target or len(transactions) < _CHANGE_TX_LIMIT:
                break
            cursor = next_tx
        else:
            raise ValueError("projection change-feed page budget reached")

    _projection_check()
    projection_timeout(timeout)
    if target is None:
        raise ValueError("projection has no change-feed proof")
    scope["epoch"] = epoch
    if membership_changed or changed:
        _forget_projection(scope)
        if membership_changed:
            if not membership_changed.intersection(entities) and len(membership_changed) <= 128:
                raise UnselectedMembershipChanges(membership_changed, changed, (store, target))
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


def projection_pause(budget):
    """Yield between recovery attempts, inside the existing time allowance."""
    delay = min(.1 * 2 ** budget.get("pauses", 0), .2)
    if budget["deadline"] - time.monotonic() <= delay:
        return False
    time.sleep(delay)
    budget["pauses"] = budget.get("pauses", 0) + 1
    return True


def repair_entities(change):
    scope = _PROJECTION.get()
    budget = scope["budget"]
    if budget["remaining"] <= 0:
        raise ValueError("owner projection retry budget reached")
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


class UnselectedMembershipChanges(EntityChanges):
    """Unselected subjects whose candidate/guard relation needs revalidation."""

    def __init__(self, membership, entities, mark):
        super().__init__(entities, mark)
        self.membership = frozenset(membership)


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


def _projection_check(server=None):
    scope = _PROJECTION.get()
    if scope is not None:
        if scope["failure"] is not None:
            raise scope["failure"]
        if (server is not None and scope["server"] is not None
                and scope["server"] != server.rstrip("/")):
            scope["failure"] = ValueError("projection cannot reuse a watermark across servers")
            raise scope["failure"]
    return scope


def _watermark(server: str, timeout: int, opener) -> tuple[str, int]:
    scope = _projection_check(server)
    if scope is None:
        return _watermark_live(server, timeout, opener)
    projection_timeout(timeout)
    server = server.rstrip("/")
    if scope["watermark"] is None:
        try:
            mark = _watermark_live(server, timeout, opener)
            _projection_check()
        except Exception as error:
            scope["failure"] = error
            raise
        scope["server"], scope["watermark"] = server, mark
    return scope["watermark"]


def _watermark_live(server: str, timeout: int, opener) -> tuple[str, int]:
    while True:
        try:
            return _watermark_once(server, projection_timeout(timeout), opener)
        except (TimeoutError, URLError) as error:
            timed_out = isinstance(error, TimeoutError) or isinstance(error.reason, TimeoutError)
            scope = _PROJECTION.get()
            budget = scope.get("budget") if scope is not None else None
            if not timed_out or budget is None or budget["remaining"] <= 0:
                raise
            # The request cap remains min(timeout, 2). Recovery consumes the
            # same tokens as a full restart or entity repair; no inner retry
            # loop can multiply the projection's admission/time budget.
            budget["remaining"] -= 1
            if not projection_pause(budget):
                raise


def _watermark_once(server: str, timeout: int, opener) -> tuple[str, int]:
    headers = {"X-Quipu-Client": "seeds", **read_headers()}
    headers["X-Quipu-Operation"] = "cache-watermark"
    request = Request(server.rstrip("/") + "/watermark", headers=headers)
    with open_read(server, request, timeout=min(timeout, 2), opener=opener) as response:
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


def _cached(path: Path, watermark, validate, *, max_age=_MAX_AGE, retain=False):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077 or info.st_size > _LIMIT):
                return None
            value = json.load(stream)
        age = time.time() - value["created"]
        observed = value.get("watermark")
        retained = (retain and _PROJECTION.get() is not None and watermark is not None
                    and isinstance(observed, list) and len(observed) == 2
                    and observed[0] == watermark[0] and type(observed[1]) is int
                    and 0 <= observed[1] <= watermark[1])
        if (value.get("schema") != 1 or value.get("key") != path.stem[5:]
                or (observed != (list(watermark) if watermark is not None else None)
                    and not retained)
                or not 0 <= age < max_age):
            return None
        result = validate(value["result"])
        if retained:
            _projection_mark(tuple(observed))
        return result
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
    # aegis-jve J3: inside stale_ok(), a fresh-enough answer costs no request.
    hit, publish = stale_lookup([server, query], validate)
    if hit is not None:
        return hit
    def current():
        # Recheck after any flight wait: another caller may have observed busy.
        quipu_busy.gate(server)
        try:
            return _read(server, query, timeout, opener=opener, fetch=fetch, validate=validate)
        except HTTPError as error:
            quipu_busy.observe(server, error)
            raise

    if publish is None:
        return current()
    quipu_busy.gate(server)  # Background callers already know not to wait.
    from .seeds_read_flight import coalesce
    return coalesce(_directory(), [server, query], timeout,
                    lookup=lambda: stale_lookup([server, query], validate), fetch=current)


def _read(server: str, query: str, timeout: int, *, opener, fetch, validate):
    # A projection owns its retry boundary: never keep its earlier fields and
    # retry just one query against a newer snapshot.
    scope = _projection_check(server)
    if scope is not None and not _DIRECT_READS.get() and scope["mark"] is None:
        _projection_mark(_watermark(server, timeout, opener))
    attempts = 1 if _READ_SNAPSHOT.get()[0] or scope is not None else 3
    for attempt in range(attempts):
        try:
            result = _read_once(server, query, timeout, opener=opener,
                                fetch=fetch, validate=validate)
            _projection_check()
            return result
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
    fence_age = _stale_fence_age()
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
            before = (scope["mark"] if scope is not None else
                      _cached(mark_path, None, valid_mark,
                              max_age=max(_WATERMARK_MAX_AGE, fence_age)))
            hit = _cached(path, before, validate, retain=_RETAIN_CANDIDATES.get()) if before is not None else None
        if before is None:
            before = (scope["mark"] if scope is not None else
                      _watermark(server, timeout, opener))
            with _locked(directory, key):
                _publish(directory, mark_path, None, before)
                hit = _cached(path, before, validate, retain=_RETAIN_CANDIDATES.get())
    except ReadBudgetRefused:
        raise  # A quota refusal is not a cache failure or permission to drop the fence.
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
        if scope is not None and _RETAIN_CANDIDATES.get():
            scope["pending"].append((directory, path, mark_path, hit))
        return hit

    if scope is not None:
        _projection_mark(before)
        result = fetch()
        scope["pending"].append((directory, path, mark_path, result))
        return result  # The whole projection owns the post-read proof.

    result = fetch()  # Never swallow a wire or completeness refusal.
    if fence_age > 0:
        # Bounded-staleness answer: the caller publishes it to the stale
        # tier only. Without an after-observation it cannot certify an
        # exact entry, so the exact cache is left untouched.
        return result
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
