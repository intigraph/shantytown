"""Opt-in real native store controls; no live graph or SDK fallback."""
import json
import os
import socket
import subprocess
import time
from urllib.request import Request, urlopen

import pytest

from shantytown import seeds_plate, stop_event, feed_check
from shantytown.answer import PartialAnswer
from shantytown.sd import SdTracker, StoreProof

BINARY = os.environ.get("SHANTYTOWN_TEST_QUIPU_SERVER")
G = "https://example.test/project/haul"
N, S = seeds_plate.SEEDS, seeds_plate.SCHEMA


@pytest.fixture
def native(tmp_path):
    if not BINARY:
        pytest.skip("set SHANTYTOWN_TEST_QUIPU_SERVER for isolated native fixture")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    endpoint = f"http://127.0.0.1:{port}"
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "LANG": "C.UTF-8",
           "TOKIO_WORKER_THREADS": "2", "QUIPU_AUTH_TOKEN": ""}
    config = tmp_path / ".bobbin"
    config.mkdir()
    (config / "config.toml").write_text("[quipu.embedding]\nauto_embed=false\n")
    with (tmp_path / "server.log").open("wb") as log:
        child = subprocess.Popen([BINARY, "--db", str(tmp_path / "store.db"),
                                  "--bind", f"127.0.0.1:{port}"],
                                 cwd=tmp_path, env=env, stdout=log, stderr=log)
        def post(path, data):
            request = Request(endpoint + path, data=json.dumps(data).encode(),
                              headers={"Content-Type": "application/json",
                                       "X-Quipu-Client": "agent-adhoc"})
            with urlopen(request, timeout=5) as response:
                return json.load(response)
        try:
            for _ in range(100):
                assert child.poll() is None, "native server exited"
                try:
                    with urlopen(endpoint + "/health", timeout=.2):
                        break
                except OSError:
                    time.sleep(.05)
            else:
                pytest.fail("native readiness deadline")
            for graph in (G, G + "#seeds-ephemeral"):
                post("/graph/create", {"graph": graph, "actor": "urn:test:haul"})
            def load(identifier, *, owner='"tim"', status='"in_progress"',
                     graph=G, priority="1", created='"2026-01-01T00:00:00Z"', extra=""):
                fields = [f'a <{S}Action>', f'<{S}identifier> {json.dumps(identifier)}',
                          f'<{S}name> "work"', f'<{S}agent> {owner}',
                          f'<{N}ontology/priority> {priority}']
                if status is not None:
                    fields.append(f'<{N}ontology/status> {status}')
                if created is not None:
                    fields.append(f'<{S}dateCreated> {created}')
                text = f'<{N}item/{identifier}> ' + ' ; '.join(fields) + ' . ' + extra
                post("/knot", {"graph": graph, "turtle": text})
            def tracker():
                value = SdTracker(quipu=endpoint, prefix="test")
                proof = StoreProof("fixture", None, endpoint, "test", G)
                value.prove_store = lambda: proof
                value._bd = lambda *a: pytest.fail("SDK hydration fallback")
                return value
            yield load, tracker, post
        finally:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)


def test_native_shared_ephemeral_parked_order_and_foreign_scope(native, monkeypatch):
    load, tracker, _ = native
    load("z-main")
    load("a-eph", graph=G + "#seeds-ephemeral",
         owner=f'<{N}principal/project%2Fcrew%2Ftim>')
    load("b-parked", extra=f'<{N}item/b-parked> <{N}ontology/deferUntil> "2099-01-01T00:00:00Z" .')
    for status in ('"open"', '"hooked"', '"blocked"', '"deferred"', '"closed"'):
        load("other-" + status.strip('"'), status=status)
    load("foreign", owner='"other"', priority="0")
    original = seeds_plate._query
    queries = []
    def counted(*args, **kwargs):
        queries.append(args[1])
        return original(*args, **kwargs)
    monkeypatch.setattr(seeds_plate, "_query", counted)
    rows = tracker().haul_active_rows("tim").exact()
    assert len(queries) == 4
    assert [r["id"] for r in rows] == ["a-eph", "b-parked", "z-main"]
    assert rows[1]["defer_until"] == "2099-01-01T00:00:00Z"
    assert tracker().haul_active_rows("absent").exact() == []


@pytest.mark.parametrize("field,value", [
    ("status", None), ("status", '"surprise"'),
    ("priority", '"bad"'), ("created", None),
    ("created", '"2026-01-01T00:00:00"'),
])
def test_native_unknown_owner_row_is_refused(native, field, value):
    load, tracker, _ = native
    load("positive")
    assert tracker().haul_active_rows("tim").exact()[0]["id"] == "positive"
    load("bad", **{field: value})
    with pytest.raises((PartialAnswer, RuntimeError, ValueError)):
        tracker().haul_active_rows("tim").exact()


@pytest.mark.parametrize("fault", ["truncated", "count", "offline"])
def test_native_transport_uncertainty_has_no_global_read(native, monkeypatch, tmp_path, fault):
    load, tracker, _ = native
    load("positive")
    t = tracker()
    assert t.haul_active_rows("tim").exact()[0]["id"] == "positive"
    original = seeds_plate.urlopen
    def broken(request, timeout):
        if fault == "offline":
            raise OSError("fixture offline")
        with original(request, timeout=timeout) as response:
            result = json.load(response)
        if "rows" in result:
            result["truncated" if fault == "truncated" else "count"] = True if fault == "truncated" else result["count"] + 1
        class Response:
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self, size):
                return json.dumps(result).encode()
        return Response()
    monkeypatch.setattr(seeds_plate, "urlopen", broken)
    monkeypatch.setattr(feed_check, "_br_tracker", lambda *a: t)
    monkeypatch.setattr(stop_event, "_bd_json", lambda *a, **k: pytest.fail("global read"))
    with pytest.raises((PartialAnswer, RuntimeError, ValueError, OSError)):
        stop_event._haul_active("tim", None, tmp_path, None)


def test_native_legacy_marker_retains_explicit_fallback(native):
    load, tracker, post = native
    load("old", extra=f'<{N}item/old> <{N}ontology/revision> 1 .')
    assert tracker().haul_active_rows("tim") is None
