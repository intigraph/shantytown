"""The opt-in must replace polling, and a refusal must fall back, never go empty."""
import json
import subprocess
from types import SimpleNamespace

import pytest

from shantytown import seeds_plate, seeds_push_read, seeds_read_cache


PROOF = SimpleNamespace(quipu_url="https://graph.example", graph="urn:test:board")
QUERY = "SELECT ?id WHERE { GRAPH <urn:test:board> { ?s ?p ?id } } LIMIT 10"
ROWS = {"rows": [{"id": "item-1"}], "count": 1, "truncated": False}
DIRECT = {"rows": [{"id": "direct-1"}], "count": 1, "truncated": False}


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
def test_malformed_or_partial_projection_falls_back_and_never_becomes_empty(
        monkeypatch, capsys, reply):
    monkeypatch.setenv("ST_SEEDS_PUSH_READS", "1")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=reply))
    monkeypatch.setattr(seeds_read_cache, "read", lambda *a, **k: DIRECT)
    assert seeds_plate._query(PROOF, QUERY, 30) == DIRECT
    assert "this read falls back to a direct Quipu read" in capsys.readouterr().err


@pytest.mark.parametrize("failure", ["exit", "timeout", "missing"])
def test_sdk_refusal_says_so_once_latches_and_falls_back(monkeypatch, capsys, failure):
    monkeypatch.setenv("ST_SEEDS_PUSH_READS", "1")
    calls = []
    def sdk(*args, **kw):
        calls.append(args)
        if failure == "timeout":
            raise subprocess.TimeoutExpired("sd", 5)
        if failure == "missing":
            raise FileNotFoundError("sd")
        return SimpleNamespace(returncode=1, stdout=b"{}", stderr=b"sd: push read UNKNOWN: not admitted\n")
    monkeypatch.setattr(subprocess, "run", sdk)
    direct = []
    monkeypatch.setattr(seeds_read_cache, "read",
                        lambda *a, **k: direct.append(a) or DIRECT)
    for _ in range(5):
        assert seeds_plate._query(PROOF, QUERY, 30) == DIRECT
    # One SDK attempt: a hung reader must not cost its 5s timeout on every read.
    assert len(calls) == 1 and len(direct) == 5
    err = capsys.readouterr().err
    assert err.count("seeds push read refused") == 1
    assert "UNKNOWN" in err
    # The latch is per binding: another board still tries its projection.
    other = SimpleNamespace(quipu_url=PROOF.quipu_url, graph="urn:test:other")
    seeds_plate._query(other, QUERY, 30)
    assert len(calls) == 2


def _counting_sdk(calls, reply):
    def sdk(*args, **kw):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout=reply, stderr=b"")
    return sdk


@pytest.mark.parametrize("reply", [b'{"rows":[],"count":0,"truncated":true}', b"broken"])
def test_per_query_refusal_does_not_latch_the_reader(monkeypatch, capsys, reply):
    monkeypatch.setenv("ST_SEEDS_PUSH_READS", "1")
    calls = []
    monkeypatch.setattr(subprocess, "run", _counting_sdk(calls, reply))
    monkeypatch.setattr(seeds_read_cache, "read", lambda *a, **k: DIRECT)
    for _ in range(3):
        assert seeds_plate._query(PROOF, QUERY, 30) == DIRECT
    # Every read still tried the projection, and the repeated reason printed once.
    assert len(calls) == 3
    assert seeds_push_read.refused(PROOF) is None
    assert capsys.readouterr().err.count("seeds push read refused") == 1


def test_budget_refusal_does_not_latch_and_the_next_read_is_served(monkeypatch, capsys):
    monkeypatch.setenv("ST_SEEDS_PUSH_READS", "1")
    calls = []
    monkeypatch.setattr(subprocess, "run", _counting_sdk(calls, json.dumps(ROWS).encode()))
    direct = []
    monkeypatch.setattr(seeds_read_cache, "read", lambda *a, **k: direct.append(a) or DIRECT)
    huge = "SELECT ?id WHERE { " + "?s ?p ?o . " * 8000 + "} LIMIT 10"
    assert seeds_plate._query(PROOF, huge, 30) == DIRECT
    assert calls == [] and len(direct) == 1
    assert "exceeds budget" in capsys.readouterr().err
    assert seeds_push_read.refused(PROOF) is None
    assert seeds_plate._query(PROOF, QUERY, 30) == ROWS
    assert len(calls) == 1 and len(direct) == 1


def test_refusal_whose_direct_read_also_fails_is_unknown_not_empty(monkeypatch):
    monkeypatch.setenv("ST_SEEDS_PUSH_READS", "1")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=5, stdout=b"", stderr=b"sd: push read UNKNOWN: stale\n"))
    def down(*a, **k):
        raise OSError("quipu unreachable")
    monkeypatch.setattr(seeds_read_cache, "read", down)
    with pytest.raises(OSError):
        seeds_plate._query(PROOF, QUERY, 30)
    answer = seeds_plate.owner_rows(PROOF, "malcolm")
    assert not answer.complete and "unreadable" in str(answer.caveat)


def test_push_disabled_never_touches_the_sdk(monkeypatch):
    monkeypatch.setenv("ST_SEEDS_PUSH_READS", "0")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("SDK on opt-out"))
    monkeypatch.setattr(seeds_read_cache, "read", lambda *a, **k: DIRECT)
    assert seeds_plate._query(PROOF, QUERY, 30) == DIRECT


EMPTY = {"rows": [], "count": 0, "truncated": False}


def _board_reads():
    from shantytown import seeds_inbox, seeds_inbox_window
    return {
        "inbox-count": lambda: seeds_inbox_window.count(PROOF, "malcolm"),
        "inbox-window": lambda: seeds_inbox_window.page_ids(PROOF, "malcolm"),
        "inbox-marker": lambda: seeds_inbox.marker_ids(PROOF, "malcolm", "event-abc"),
        "native-schema": lambda: seeds_plate.uses_native_schema(PROOF),
    }


@pytest.mark.parametrize("name", sorted(_board_reads()))
def test_each_board_read_goes_through_the_reader_seam(monkeypatch, name):
    monkeypatch.setenv("ST_SEEDS_PUSH_READS", "1")
    seen = []
    def push(proof, query, timeout):
        seen.append(query)
        return {"result": False} if query.lstrip().startswith("ASK") else EMPTY
    monkeypatch.setattr(seeds_push_read, "read", push)
    monkeypatch.setattr(seeds_plate, "urlopen", lambda *a, **k: pytest.fail("primary HTTP"))
    monkeypatch.setattr(seeds_read_cache, "read", lambda *a, **k: pytest.fail("watermark cache"))
    _board_reads()[name]()
    assert seen


@pytest.mark.parametrize("name", sorted(_board_reads()))
def test_each_board_read_falls_back_when_the_reader_fails(monkeypatch, name):
    monkeypatch.setenv("ST_SEEDS_PUSH_READS", "1")
    def push(proof, query, timeout):
        raise ValueError("push read UNKNOWN: SDK refused (exit 5): stale")
    direct = []
    def cache(url, query, timeout, **kw):
        direct.append(query)
        return {"result": False} if query.lstrip().startswith("ASK") else EMPTY
    monkeypatch.setattr(seeds_push_read, "read", push)
    monkeypatch.setattr(seeds_read_cache, "read", cache)
    _board_reads()[name]()
    assert direct


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
        seeds_plate._validate_query(seeds_push_read.read(PROOF, "ASK {}", 30), "ASK {}")
    # In the seam the unreadable ASK is a refusal: the direct read answers.
    monkeypatch.setattr(seeds_read_cache, "read", lambda *a, **k: {"result": True})
    assert seeds_plate._query(PROOF, "ASK { ?s ?p ?o }", 30) == {"result": True}


# aegis-ygz: the az3d re-enable was rolled back when `st anchor malcolm
# --short` (first seen in a Codex pane) reported "owner plate unreadable: push
# read UNKNOWN: SDK refused or response exceeded budget". sd had refused for
# its freshness budget and said so on stderr, which this layer discarded.
FRESHNESS = (b"sd: push read UNKNOWN: IPC binding or end-to-end freshness mismatch;"
             b" no primary polling fallback\n")


def test_owner_plate_names_the_sdk_refusal_reason(monkeypatch, capsys):
    monkeypatch.setenv("ST_SEEDS_PUSH_READS", "1")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=5, stdout=b"", stderr=FRESHNESS))
    monkeypatch.setattr(seeds_plate, "urlopen", lambda *a, **k: pytest.fail("raw HTTP"))
    def down(*a, **k):
        raise OSError("direct read down")
    monkeypatch.setattr(seeds_read_cache, "read", down)
    answer = seeds_plate.owner_rows(PROOF, "malcolm")
    assert not answer.complete and "owner plate unreadable" in str(answer.caveat)
    err = capsys.readouterr().err
    assert "SDK refused (exit 5)" in err
    assert "end-to-end freshness mismatch" in err
    assert "exceeded budget" not in err


def test_refusal_reason_is_one_bounded_line_and_budget_is_separate(monkeypatch):
    monkeypatch.setenv("ST_SEEDS_PUSH_READS", "1")
    noisy = b"warning: x\n" + b"sd: push read UNKNOWN: " + b"y" * 5000 + b"\r\n\n"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=5, stdout=b"", stderr=noisy))
    with pytest.raises(ValueError) as refused:
        seeds_push_read.read(PROOF, QUERY, 30)
    message = str(refused.value)
    assert "\n" not in message and "warning" not in message
    assert len(message) < 400
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=1, stdout=b"{}", stderr=None))
    with pytest.raises(ValueError, match=r"exit 1\): no reason given"):
        seeds_push_read.read(PROOF, QUERY, 30)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout=b" " * (8 * 1024 * 1024 + 1), stderr=b""))
    with pytest.raises(ValueError, match="response exceeded budget"):
        seeds_push_read.read(PROOF, QUERY, 30)
