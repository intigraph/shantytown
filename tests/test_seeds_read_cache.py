"""Window-bounded metadata shares work; expired observations cannot hide refusals."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from shantytown import seeds_plate, seeds_read_cache


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.delenv("ST_SEEDS_READ_CACHE", raising=False)
    state = dict(store="fixture-store", tx=10, queries=0, watermarks=0,
                 value="before", fail_mark=False, fail_query=False,
                 malformed=False, mutate=False, delay=0)
    mutex = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def answer(self, value, code=200):
            body = json.dumps(value).encode()
            self.send_response(code)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            assert self.path == "/watermark"
            with mutex:
                state["watermarks"] += 1
                value = dict(store_id=state["store"], watermark_tx=state["tx"])
            self.answer(value, 503 if state["fail_mark"] else 200)

        def do_POST(self):
            assert self.path == "/query"
            query = json.loads(self.rfile.read(int(self.headers["Content-Length"])))['query']
            with mutex:
                state["queries"] += 1
                value = state["value"]
            time.sleep(state["delay"])
            if state["fail_query"]:
                self.answer({"error": "fixture refusal"}, 408)
                return
            if state["malformed"]:
                self.answer({"rows": [], "count": 1, "truncated": False})
                return
            if state["mutate"]:
                state["tx"] += 1
                state["value"] = "after"
                state["mutate"] = False
            self.answer({"result": False} if query.startswith("ASK") else
                        {"rows": [{"value": value, "query": query}], "count": 1,
                         "truncated": False})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    proof = SimpleNamespace(quipu_url=f"http://127.0.0.1:{server.server_port}")
    try:
        yield proof, state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def read(proof, query="SELECT owner-one", **kwargs):
    return seeds_plate._query(proof, query, 5, **kwargs)


def entries():
    return list(seeds_read_cache._directory().glob("read-*.json"))


def test_bounded_routing_reads_never_attempt_watermark_and_keep_six_read_cap(service):
    from shantytown.review_routing import read_budget, ReadBudgetExceeded
    proof, state = service
    with read_budget() as usage:
        for _ in range(6):
            assert read(proof)["rows"][0]["value"] == "before"
        with pytest.raises(ReadBudgetExceeded):
            read(proof)
    assert usage == {"reads": 6, "timeouts": 0}
    assert state["queries"] == 6 and state["watermarks"] == 0
    assert read(proof)["rows"][0]["value"] == "before"
    assert state["queries"] == 7 and state["watermarks"] == 2
    read(proof)
    assert state["queries"] == 7 and state["watermarks"] == 2


def test_direct_reads_restore_after_exception_and_do_not_change_other_threads(service):
    proof, state = service
    with pytest.raises(RuntimeError, match="fixture"):
        with seeds_read_cache.direct_reads():
            read(proof)
            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(read, proof).result()
            assert state["queries"] == 2 and state["watermarks"] == 2
            raise RuntimeError("fixture")
    read(proof)
    assert state["queries"] == 2 and state["watermarks"] == 2


def test_same_probe_before_after_and_current_positive_control(service, monkeypatch):
    proof, state = service
    monkeypatch.setenv("ST_SEEDS_READ_CACHE", "0")
    for _ in range(12):
        assert read(proof)["rows"][0]["value"] == "before"
    assert state["queries"] == 12
    monkeypatch.delenv("ST_SEEDS_READ_CACHE")
    state["queries"] = 0
    for _ in range(12):
        assert read(proof)["rows"][0]["value"] == "before"
    assert state["queries"] == 1
    assert state["watermarks"] == 2  # one shared window, plus the post-fetch proof


def test_new_transaction_invalidates_after_watermark_window(service, monkeypatch):
    monkeypatch.setattr(seeds_read_cache, "_WATERMARK_MAX_AGE", 0)
    proof, state = service
    read(proof)
    state.update(tx=11, value="changed")
    assert read(proof)["rows"][0]["value"] == "changed"
    assert state["queries"] == 2


def test_new_store_at_same_transaction_cannot_reuse_old_rows(service, monkeypatch):
    monkeypatch.setattr(seeds_read_cache, "_WATERMARK_MAX_AGE", 0)
    proof, state = service
    read(proof)
    state.update(store="replacement", value="different")
    assert read(proof)["rows"][0]["value"] == "different"
    assert state["queries"] == 2


def test_write_during_fetch_does_not_publish_a_mislabeled_result(service):
    proof, state = service
    state["mutate"] = True
    assert read(proof)["rows"][0]["value"] == "after"
    assert len(entries()) == 1
    assert state["queries"] == 2


def test_metadata_failure_reads_fresh_never_falls_back_to_cached_success(service, monkeypatch):
    monkeypatch.setattr(seeds_read_cache, "_WATERMARK_MAX_AGE", 0)
    proof, state = service
    read(proof)
    state.update(fail_mark=True, value="fresh")
    assert read(proof)["rows"][0]["value"] == "fresh"
    state["fail_query"] = True
    with pytest.raises(HTTPError):
        read(proof)
    assert state["queries"] == 3


def test_incomplete_response_never_enters_cache(service):
    proof, state = service
    state["malformed"] = True
    for _ in range(2):
        with pytest.raises(ValueError, match="completeness"):
            read(proof)
    assert state["queries"] == 2
    assert entries() == []
    state["malformed"] = False
    assert read(proof)["count"] == 1


def test_false_ask_is_valid_cached_data_with_a_populated_read_control(service):
    proof, state = service
    assert read(proof, "ASK schema") == {"result": False}
    assert read(proof, "ASK schema") == {"result": False}
    assert read(proof)["count"] == 1
    assert state["queries"] == 2


def test_owner_and_graph_query_constants_are_distinct_keys(service):
    proof, state = service
    for query in ["SELECT owner-one graph-one", "SELECT owner-two graph-one",
                  "SELECT owner-one graph-two"]:
        assert read(proof, query)["rows"][0]["query"] == query
        assert read(proof, query)["rows"][0]["query"] == query
    assert state["queries"] == 3


def test_corrupt_cache_is_a_miss_not_a_failed_or_empty_answer(service):
    proof, state = service
    read(proof)
    entries()[0].write_text("{}")
    assert read(proof)["count"] == 1
    assert state["queries"] == 2


def test_expired_entry_requires_real_execution_even_at_same_watermark(service):
    proof, state = service
    read(proof)
    path = entries()[0]
    value = json.loads(path.read_text())
    value["created"] = 0
    path.write_text(json.dumps(value))
    read(proof)
    assert state["queries"] == 2


def test_explicit_profile_bypasses_cache(service):
    proof, state = service
    read(proof, verbose=True)
    read(proof, verbose=True)
    assert state["queries"] == 2
    assert state["watermarks"] == 0


def test_cache_storage_failure_preserves_original_reader(service, monkeypatch):
    proof, state = service
    def unavailable():
        raise OSError("fixture unavailable cache")
    monkeypatch.setattr(seeds_read_cache, "_directory", unavailable)
    assert read(proof)["count"] == 1
    assert state["queries"] == 1


def test_simultaneous_processes_do_not_hold_cache_lock_across_http(service):
    proof, state = service
    state["delay"] = .1
    code = ("from types import SimpleNamespace; from shantytown import seeds_plate; "
            "assert seeds_plate._query(SimpleNamespace(quipu_url="
            + repr(proof.quipu_url) + "),'SELECT concurrent',5)['count']==1")
    def child(_):
        return subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).parents[1],
                              env=os.environ.copy(), capture_output=True, text=True, timeout=10)
    with ThreadPoolExecutor(max_workers=6) as workers:
        results = list(workers.map(child, range(6)))
    assert all(r.returncode == 0 for r in results), [r.stderr for r in results]
    assert 1 <= state["queries"] <= 6


def test_private_bounded_cache(service, monkeypatch):
    proof, _ = service
    monkeypatch.setattr(seeds_read_cache, "_ENTRIES", 3)
    for n in range(5):
        read(proof, f"SELECT owner-{n}")
    assert len(entries()) == 3
    assert all(p.stat().st_mode & 0o077 == 0 for p in entries())


def test_symlink_cache_is_not_followed(service, tmp_path):
    proof, state = service
    read(proof)
    path = entries()[0]
    outside = tmp_path / "outside.json"
    outside.write_bytes(path.read_bytes())
    original = outside.read_bytes()
    path.unlink()
    path.symlink_to(outside)
    state["value"] = "fresh"
    assert read(proof)["rows"][0]["value"] == "fresh"
    assert outside.read_bytes() == original
    assert state["queries"] == 2


def test_transaction_regression_is_a_miss(service, monkeypatch):
    monkeypatch.setattr(seeds_read_cache, "_WATERMARK_MAX_AGE", 0)
    proof, state = service
    read(proof)
    state.update(tx=9, value="restored")
    assert read(proof)["rows"][0]["value"] == "restored"
    assert state["queries"] == 2

def test_watermark_window_is_bounded_and_shared_across_queries(service, monkeypatch):
    proof, state = service
    clock = [1000.]
    monkeypatch.setattr(seeds_read_cache.time, "time", lambda: clock[0])
    read(proof)
    read(proof, "SELECT another-owner")
    assert state["watermarks"] == 3  # before first + after each distinct query
    state.update(tx=11, value="changed")
    assert read(proof)["rows"][0]["value"] == "before"
    assert state["watermarks"] == 3
    clock[0] += 1
    assert read(proof)["rows"][0]["value"] == "changed"
    assert state["watermarks"] == 5


def test_corrupt_watermark_window_does_not_authorize_cached_success(service):
    proof, state = service
    read(proof)
    next(seeds_read_cache._directory().glob("mark-*.json")).write_text("{}")
    state.update(tx=11, value="changed")
    assert read(proof)["rows"][0]["value"] == "changed"


def test_http_fetch_and_watermarks_never_hold_the_local_lock(service, monkeypatch):
    import fcntl
    proof, state = service
    original = seeds_read_cache._watermark
    def assert_unlocked():
        for path in seeds_read_cache._directory().glob("lock-*"):
            with path.open("rb") as file:
                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(file.fileno(), fcntl.LOCK_UN)
    def watermark(*args):
        assert_unlocked()
        return original(*args)
    monkeypatch.setattr(seeds_read_cache, "_watermark", watermark)
    query = "SELECT unlocked"
    def fetch():
        assert_unlocked()
        return seeds_plate._query_wire(proof, query, 5)
    result = seeds_read_cache.read(proof.quipu_url, query, 5,
                                  opener=seeds_plate.urlopen, fetch=fetch,
                                  validate=lambda result: seeds_plate._validate_query(result, query))
    assert result["count"] == 1
    assert state["queries"] == 1 and state["watermarks"] == 2


def test_projection_refuses_change_between_individually_stable_queries(service, monkeypatch):
    proof, state = service
    monkeypatch.setattr(seeds_read_cache, "_WATERMARK_MAX_AGE", 0)
    with seeds_read_cache.consistent_reads():
        assert read(proof, "SELECT candidates")["count"] == 1
        state.update(tx=11, value="after")
        with pytest.raises(ValueError, match="across projection"):
            read(proof, "SELECT fields")
    # The scope must restore; a new projection may use the new snapshot.
    with seeds_read_cache.consistent_reads():
        assert read(proof, "SELECT fields")["rows"][0]["value"] == "after"


def test_single_read_refetches_after_one_watermark_move(service):
    proof, state = service
    state["mutate"] = True
    assert read(proof)["rows"][0]["value"] == "after"
    assert state["queries"] == 2


def test_single_read_refuses_when_watermark_never_settles(service):
    proof, state = service
    def moving_fetch():
        result = seeds_plate._query_wire(proof, "SELECT moving", 5)
        state["tx"] += 1
        return result
    with pytest.raises(ValueError, match="watermark moved"):
        seeds_read_cache.read(proof.quipu_url, "SELECT moving", 5,
                              opener=seeds_plate.urlopen, fetch=moving_fetch,
                              validate=lambda value: value)
    assert state["queries"] == 3
    assert entries() == []


def test_store_replacement_during_read_is_not_a_retryable_transaction(service):
    proof, state = service
    def replacement_fetch():
        result = seeds_plate._query_wire(proof, "SELECT replacement", 5)
        state["store"] = "replacement-store"
        return result
    with pytest.raises(ValueError, match="store changed"):
        seeds_read_cache.read(proof.quipu_url, "SELECT replacement", 5,
                              opener=seeds_plate.urlopen, fetch=replacement_fetch,
                              validate=lambda value: value)
    assert state["queries"] == 1
    assert entries() == []


# aegis-jve J3: bounded-staleness tier for per-turn crew reads.

def test_stale_tier_is_off_outside_stale_ok(service, monkeypatch):
    monkeypatch.setattr(seeds_read_cache, "_WATERMARK_MAX_AGE", 0)
    proof, state = service
    read(proof)
    state.update(tx=11, value="changed")
    assert read(proof)["rows"][0]["value"] == "changed"
    assert state["queries"] == 2


def test_stale_ok_serves_a_moving_board_without_requests_until_ttl(service, monkeypatch):
    monkeypatch.setattr(seeds_read_cache, "_WATERMARK_MAX_AGE", 0)
    proof, state = service
    with seeds_read_cache.stale_ok():
        assert read(proof)["rows"][0]["value"] == "before"
        used = state["queries"] + state["watermarks"]
        state.update(tx=11, value="changed")  # someone else wrote
        for _ in range(10):
            assert read(proof)["rows"][0]["value"] == "before"
        assert state["queries"] + state["watermarks"] == used  # zero requests
    # older than the TTL: refetched
    real = time.time
    monkeypatch.setattr(seeds_read_cache.time, "time", lambda: real() + 61)
    with seeds_read_cache.stale_ok():
        assert read(proof)["rows"][0]["value"] == "changed"


def test_own_write_invalidates_the_stale_tier(service, monkeypatch):
    monkeypatch.setattr(seeds_read_cache, "_WATERMARK_MAX_AGE", 0)
    proof, state = service
    with seeds_read_cache.stale_ok():
        read(proof)
        state.update(tx=11, value="changed")
        seeds_read_cache.invalidate_stale()
        assert read(proof)["rows"][0]["value"] == "changed"


def test_a_fetch_overlapping_a_write_is_not_published(service, monkeypatch):
    proof, state = service
    with seeds_read_cache.stale_ok():
        hit, publish = seeds_read_cache.stale_lookup([proof.quipu_url, "Q"], lambda v: v)
        assert hit is None and publish is not None
        seeds_read_cache.invalidate_stale()  # a write lands mid-fetch
        publish({"rows": [], "count": 0, "truncated": False})
        hit, _ = seeds_read_cache.stale_lookup([proof.quipu_url, "Q"], lambda v: v)
        assert hit is None


@pytest.mark.parametrize("env", [("ST_SEEDS_STALE_TTL", "0"), ("ST_SEEDS_READ_CACHE", "0")])
def test_stale_tier_rollback_switches(service, monkeypatch, env):
    monkeypatch.setattr(seeds_read_cache, "_WATERMARK_MAX_AGE", 0)
    monkeypatch.setenv(*env)
    proof, state = service
    with seeds_read_cache.stale_ok():
        read(proof)
        state.update(tx=11, value="changed")
        assert read(proof)["rows"][0]["value"] == "changed"


def test_stale_ttl_is_capped_and_unparseable_disables(monkeypatch):
    monkeypatch.setenv("ST_SEEDS_STALE_TTL", "600")
    assert seeds_read_cache.stale_ttl() == 60.0
    monkeypatch.setenv("ST_SEEDS_STALE_TTL", "soon")
    assert seeds_read_cache.stale_ttl() == 0.0
    monkeypatch.delenv("ST_SEEDS_STALE_TTL")
    assert seeds_read_cache.stale_ttl() == 60.0


def test_exact_scopes_never_take_the_stale_tier(service):
    proof, state = service
    with seeds_read_cache.stale_ok(), seeds_read_cache.direct_reads():
        assert seeds_read_cache.stale_lookup([proof.quipu_url, "Q"], lambda v: v) == (None, None)
    with seeds_read_cache.stale_ok(), seeds_read_cache.projection_reads():
        assert seeds_read_cache.stale_lookup([proof.quipu_url, "Q"], lambda v: v) == (None, None)


@pytest.mark.real_store  # subprocess.run is replaced below; nothing reaches a store
def test_sd_list_shares_one_child_per_ttl_and_writes_invalidate(tmp_path, monkeypatch):
    from shantytown import sd as sd_mod
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.delenv("ST_SEEDS_READ_CACHE", raising=False)
    monkeypatch.delenv("ST_SEEDS_STALE_TTL", raising=False)
    tracker = sd_mod.SdTracker(repo=str(tmp_path), prefix="aegis")
    monkeypatch.setattr(tracker, "prove_store", lambda: None)
    monkeypatch.setattr(type(tracker), "_bin", property(lambda self: "sd"))
    monkeypatch.setattr(tracker, "_location", lambda: [])
    calls = []

    def fake_run(cmd, **_kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"n": len(calls)}), "")

    monkeypatch.setattr(sd_mod.subprocess, "run", fake_run)
    import shantytown.advise_signing as signing
    monkeypatch.setattr(signing, "run", lambda cmd, **kw: fake_run(cmd))
    tracker._bd("list", "--assignee", "wu", "--json")
    tracker._bd("list", "--assignee", "wu", "--json")
    assert len(calls) == 2  # outside stale_ok(): always live
    calls.clear()
    scope = seeds_read_cache.stale_ok()
    scope.__enter__()
    first = tracker._bd("list", "--assignee", "wu", "--json")
    second = tracker._bd("list", "--assignee", "wu", "--json")
    assert first.stdout == second.stdout and len(calls) == 1
    tracker._bd("show", "aegis-1", "--json")  # a read: no invalidation
    tracker._bd("list", "--assignee", "wu", "--json")
    assert sum(1 for c in calls if "list" in c) == 1
    tracker._bd("update", "aegis-1", "--status", "open")  # a write
    third = tracker._bd("list", "--assignee", "wu", "--json")
    assert sum(1 for c in calls if "list" in c) == 2 and third.stdout != first.stdout
    other = tracker._bd("list", "--assignee", "ian", "--json")
    assert sum(1 for c in calls if "list" in c) == 3 and other.returncode == 0
    scope.__exit__(None, None, None)


# Review of #643: the three blocking findings.

def test_own_write_cannot_republish_pre_write_data_through_the_exact_cache(service):
    # Default 1 s watermark window (not 0): the exact cache would still
    # certify the pre-write answer unless invalidation drops the marks.
    proof, state = service
    with seeds_read_cache.stale_ok():
        assert read(proof)["rows"][0]["value"] == "before"
        state.update(tx=11, value="changed")  # our own write commits
        seeds_read_cache.invalidate_stale()
        assert read(proof)["rows"][0]["value"] == "changed"
        assert read(proof)["rows"][0]["value"] == "changed"  # and stays fresh


def _fake_tracker(tmp_path, monkeypatch):
    from shantytown import sd as sd_mod
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.delenv("ST_SEEDS_READ_CACHE", raising=False)
    monkeypatch.delenv("ST_SEEDS_STALE_TTL", raising=False)
    tracker = sd_mod.SdTracker(repo=str(tmp_path), prefix="aegis")
    monkeypatch.setattr(tracker, "prove_store", lambda: None)
    monkeypatch.setattr(type(tracker), "_bin", property(lambda self: "sd"))
    monkeypatch.setattr(tracker, "_location", lambda: [])
    calls = []

    def fake_run(cmd, **kw):
        calls.append((cmd, kw.get("cwd"), dict(kw.get("env") or {})))
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"n": len(calls)}), "")

    monkeypatch.setattr(sd_mod.subprocess, "run", fake_run)
    return sd_mod, tracker, calls


@pytest.mark.real_store  # subprocess.run is replaced; nothing reaches a store
def test_sd_cache_key_separates_store_identity_cwd_and_pinned_config(tmp_path, monkeypatch):
    sd_mod, tracker, calls = _fake_tracker(tmp_path, monkeypatch)
    with seeds_read_cache.stale_ok():
        tracker._bd("list", "--json")
        monkeypatch.setenv("SEEDS_STORE", "/other/store")  # a different store
        tracker._bd("list", "--json")
        monkeypatch.setenv("QUIPU_AGENT", "someone-else")  # a different identity
        tracker._bd("list", "--json")
        tracker._bd_in(str(tmp_path / "elsewhere"), "list", "--json")  # different cwd
        import shantytown.actor_identity as ai
        monkeypatch.setattr(ai, "config_environment", lambda: {"SEEDS_CONFIG": "/pinned"})
        tracker._bd("list", "--json")  # pinned config
        assert len(calls) == 5
        tracker._bd("list", "--json")  # same everything: shared
        assert len(calls) == 5


@pytest.mark.real_store
def test_a_write_that_times_out_still_invalidates(tmp_path, monkeypatch):
    sd_mod, tracker, calls = _fake_tracker(tmp_path, monkeypatch)
    with seeds_read_cache.stale_ok():
        tracker._bd("list", "--json")
        import shantytown.advise_signing as signing

        def timeout(cmd, **_kw):
            raise subprocess.TimeoutExpired(cmd, 1)

        monkeypatch.setattr(sd_mod.subprocess, "run", timeout)
        monkeypatch.setattr(signing, "run", lambda cmd, **kw: timeout(cmd))
        with pytest.raises(subprocess.TimeoutExpired):
            tracker._bd("update", "aegis-1", "--status", "open")
        hit, _ = seeds_read_cache.stale_lookup(["anything"], lambda v: v)
        assert hit is None
    # the earlier list answer is no longer served
    monkeypatch.setattr(sd_mod.subprocess, "run",
                        lambda cmd, **kw: calls.append((cmd, None, {})) or
                        subprocess.CompletedProcess(cmd, 0, '{"n": 99}', ""))
    with seeds_read_cache.stale_ok():
        assert tracker._bd("list", "--json").stdout == '{"n": 99}'


def test_failed_generation_write_drops_entries_and_unwritable_cache_disables(service, monkeypatch):
    proof, state = service
    with seeds_read_cache.stale_ok():
        _, publish = seeds_read_cache.stale_lookup(["k"], lambda v: v)
        publish({"rows": [], "count": 0, "truncated": False})
        assert seeds_read_cache.stale_lookup(["k"], lambda v: v)[0] is not None

        def broken(*_a, **_k):
            raise OSError("disk full")

        monkeypatch.setattr(seeds_read_cache.tempfile, "mkstemp", broken)
        seeds_read_cache.invalidate_stale()
        assert seeds_read_cache.stale_lookup(["k"], lambda v: v)[0] is None
        monkeypatch.undo()
        directory = seeds_read_cache._directory()
        directory.chmod(0o500)
        try:
            assert seeds_read_cache.stale_lookup(["k"], lambda v: v) == (None, None)
        finally:
            directory.chmod(0o700)


# aegis-jve: inside stale_ok() the exact /watermark fence is relaxed to the
# stale bound. A miss is answered by one query, an exact hit by none, and the
# exact cache is never published from a stale-scope answer.

def _advance(monkeypatch, seconds):
    real = time.time
    monkeypatch.setattr(seeds_read_cache.time, "time", lambda: real() + seconds)


def test_stale_scope_miss_reuses_a_recent_mark_and_skips_the_after_fence(service, monkeypatch):
    proof, state = service
    read(proof)  # exact read observes the watermark (before + after)
    assert state["watermarks"] == 2
    _advance(monkeypatch, 30)  # mark older than the exact 1s, within the 60s stale bound
    with seeds_read_cache.stale_ok():
        assert read(proof, "SELECT owner-two")["rows"][0]["query"] == "SELECT owner-two"
    assert state["watermarks"] == 2  # no before/after fence for a stale-scope miss
    assert state["queries"] == 2


def test_stale_scope_exact_hit_with_recent_mark_costs_no_request(service, monkeypatch):
    proof, state = service
    read(proof)
    used = state["queries"] + state["watermarks"]
    _advance(monkeypatch, 30)
    with seeds_read_cache.stale_ok():
        assert read(proof)["rows"][0]["value"] == "before"
    assert state["queries"] + state["watermarks"] == used


def test_stale_scope_answer_never_publishes_the_exact_cache(service, monkeypatch):
    proof, state = service
    read(proof)
    _advance(monkeypatch, 30)
    with seeds_read_cache.stale_ok():
        read(proof, "SELECT owner-two")
    assert not [p for p in entries() if "owner-two" in p.read_text()]
    # outside the scope the exact path is unchanged: fresh mark, full fence
    before = state["watermarks"]
    read(proof, "SELECT owner-two")
    assert state["watermarks"] == before + 2


def test_stale_scope_mark_older_than_the_bound_is_reobserved(service, monkeypatch):
    proof, state = service
    read(proof)
    _advance(monkeypatch, 61)
    with seeds_read_cache.stale_ok():
        read(proof, "SELECT owner-two")
    assert state["watermarks"] == 3  # one fresh before-observation, still no after-fence


def test_own_write_drops_the_mark_so_a_stale_scope_reobserves(service, monkeypatch):
    proof, state = service
    read(proof)
    _advance(monkeypatch, 30)
    seeds_read_cache.invalidate_stale()  # an own write
    with seeds_read_cache.stale_ok():
        read(proof, "SELECT owner-two")
    assert state["watermarks"] == 3


def test_stale_scope_fence_relaxation_obeys_rollback(service, monkeypatch):
    proof, state = service
    monkeypatch.setenv("ST_SEEDS_STALE_TTL", "0")
    read(proof)
    _advance(monkeypatch, 30)
    with seeds_read_cache.stale_ok():
        read(proof, "SELECT owner-two")
    assert state["watermarks"] == 4  # exact behaviour: before + after again
