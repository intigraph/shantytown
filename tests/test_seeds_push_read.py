"""The opt-in must replace polling, and be capable of refusing."""
import json
import subprocess
from types import SimpleNamespace

import pytest

from shantytown import seeds_plate, seeds_push_read, seeds_read_cache


PROOF = SimpleNamespace(quipu_url="https://graph.example", graph="urn:test:board")
QUERY = "SELECT ?id WHERE { GRAPH <urn:test:board> { ?s ?p ?id } } LIMIT 10"
ROWS = {"rows": [{"id": "item-1"}], "count": 1, "truncated": False}


def test_repeated_reads_never_touch_primary_or_watermark(monkeypatch):
    monkeypatch.setenv("ST_SEEDS_PUSH_READS", "1")
    calls = []
    def sdk(argv, **kw):
        calls.append((argv, json.loads(kw["input"])))
        return SimpleNamespace(returncode=0, stdout=json.dumps(ROWS).encode())
    monkeypatch.setattr(subprocess, "run", sdk)
    monkeypatch.setattr(seeds_plate, "urlopen", lambda *a, **k: pytest.fail("primary HTTP"))
    monkeypatch.setattr(seeds_read_cache, "read", lambda *a, **k: pytest.fail("watermark cache"))
    for _ in range(20):
        assert seeds_plate._query(PROOF, QUERY, 30) == ROWS
    assert len(calls) == 20
    assert all(argv[-1] == "read-stream-query" and body == {"query": QUERY}
               for argv, body in calls)
    assert all(argv[1:5] == ["--quipu", PROOF.quipu_url, "--graph", PROOF.graph]
               for argv, _ in calls)


@pytest.mark.parametrize("reply", [b"{}", b"[]", b"broken",
    b'{"rows":[],"count":0,"truncated":true}',
    b'{"rows":[],"count":1,"truncated":false}'])
def test_malformed_or_partial_projection_never_becomes_empty(monkeypatch, reply):
    monkeypatch.setenv("ST_SEEDS_PUSH_READS", "1")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=reply))
    monkeypatch.setattr(seeds_plate, "urlopen", lambda *a, **k: pytest.fail("fallback"))
    with pytest.raises((ValueError, TypeError)):
        seeds_plate._query(PROOF, QUERY, 30)


@pytest.mark.parametrize("failure", ["exit", "timeout", "missing"])
def test_sdk_refusals_do_not_poll(monkeypatch, failure):
    monkeypatch.setenv("ST_SEEDS_PUSH_READS", "1")
    def sdk(*args, **kw):
        if failure == "timeout":
            raise subprocess.TimeoutExpired("sd", 5)
        if failure == "missing":
            raise FileNotFoundError("sd")
        return SimpleNamespace(returncode=1, stdout=b"{}")
    monkeypatch.setattr(subprocess, "run", sdk)
    monkeypatch.setattr(seeds_plate, "urlopen", lambda *a, **k: pytest.fail("fallback"))
    with pytest.raises(ValueError, match="UNKNOWN"):
        seeds_plate._query(PROOF, QUERY, 30)


def test_explicit_primary_scope_and_opt_out_are_retained(monkeypatch):
    monkeypatch.setenv("ST_SEEDS_PUSH_READS", "1")
    monkeypatch.setattr(seeds_push_read, "read", lambda *a: pytest.fail("push crossed admission"))
    monkeypatch.setattr(seeds_read_cache, "read", lambda *a, **k: ROWS)
    with seeds_read_cache.direct_reads():
        assert seeds_plate._query(PROOF, QUERY, 30) == ROWS
    monkeypatch.setenv("ST_SEEDS_PUSH_READS", "0")
    assert seeds_plate._query(PROOF, QUERY, 30) == ROWS


def test_profiling_and_unknown_setting_refuse(monkeypatch):
    monkeypatch.setenv("ST_SEEDS_PUSH_READS", "1")
    with pytest.raises(ValueError, match="profiling"):
        seeds_plate._query(PROOF, QUERY, 30, verbose=True)
    monkeypatch.setenv("ST_SEEDS_PUSH_READS", "maybe")
    with pytest.raises(ValueError, match="0 or 1"):
        seeds_plate._query(PROOF, QUERY, 30)


def test_false_ask_is_valid_but_missing_boolean_is_unknown(monkeypatch):
    monkeypatch.setenv("ST_SEEDS_PUSH_READS", "1")
    monkeypatch.setattr(seeds_push_read, "read", lambda *a: {"result": False})
    assert seeds_plate._query(PROOF, "ASK { ?s ?p ?o }", 30) == {"result": False}
    monkeypatch.setattr(seeds_push_read, "read", lambda *a: {"result": 0})
    with pytest.raises(ValueError, match="unreadable"):
        seeds_plate._query(PROOF, "ASK { ?s ?p ?o }", 30)
