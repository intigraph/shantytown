"""Current-watermark reads share work without hiding mutations or refusals."""
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
    assert state["watermarks"] == 13  # fresh hit checks plus both sides of miss


def test_new_transaction_immediately_invalidates(service):
    proof, state = service
    read(proof)
    state.update(tx=11, value="changed")
    assert read(proof)["rows"][0]["value"] == "changed"
    assert state["queries"] == 2


def test_new_store_at_same_transaction_cannot_reuse_old_rows(service):
    proof, state = service
    read(proof)
    state.update(store="replacement", value="different")
    assert read(proof)["rows"][0]["value"] == "different"
    assert state["queries"] == 2


def test_write_during_fetch_does_not_publish_a_mislabeled_result(service):
    proof, state = service
    state["mutate"] = True
    assert read(proof)["rows"][0]["value"] == "before"
    assert entries() == []
    assert read(proof)["rows"][0]["value"] == "after"
    assert state["queries"] == 2


def test_metadata_failure_reads_fresh_never_falls_back_to_cached_success(service):
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


def test_simultaneous_processes_share_one_query(service):
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
    assert state["queries"] == 1


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


def test_transaction_regression_is_a_miss(service):
    proof, state = service
    read(proof)
    state.update(tx=9, value="restored")
    assert read(proof)["rows"][0]["value"] == "restored"
    assert state["queries"] == 2
