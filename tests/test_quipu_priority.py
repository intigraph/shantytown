"""aegis-69x: status/poll st invocations send `X-Quipu-Priority: background`.

Quipu sheds background reads first (429 + Retry-After). Only invocations nobody
waits on may carry it; interactive commands and writes never do, and a shed
read is a could-not-look with its retry time, never a value.
"""
import io
import json
from email.message import Message
from urllib.error import HTTPError

import pytest

from shantytown import cli, quipu, quipu_busy
from shantytown.answer import CouldNotLook
from shantytown.query_identity import (background_invocation, background_reads,
                                       read_priority)

SERVER = "http://quipu.example"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.delenv("QUIPU_PRIORITY", raising=False)
    monkeypatch.setenv("ST_QUIPU_READS_PER_MINUTE", "0")


class Wire:
    """A fake urlopen that records each request and answers from a script."""

    def __init__(self, answer=None):
        self.requests = []
        self.answer = answer or (lambda request: {"rows": []})

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        result = self.answer(request)
        if isinstance(result, BaseException):
            raise result
        return io.BytesIO(json.dumps(result).encode())

    def priorities(self):
        return [r.get_header("X-quipu-priority") for r in self.requests]


def busy(code=429, retry_after="7"):
    headers = Message()
    headers["Retry-After"] = retry_after
    return HTTPError(SERVER + "/query", code, "busy", headers, io.BytesIO(b"{}"))


@pytest.fixture
def wire(monkeypatch):
    fake = Wire()
    monkeypatch.setattr(quipu.urllib.request, "urlopen", fake)
    return fake


def registry():
    return quipu.QuipuRegistry(SERVER, onto="https://example.test/")


@pytest.mark.parametrize("argv", [
    ["anchor", "me", "--short"], ["anchor", "me", "--events"], ["anchor", "me", "--harness"],
    ["crew", "--count"], ["crew", "--governor"], ["crew", "--display-snapshot"],
    ["inbox", "--count"], ["dashboard"], ["tend"], ["watch"],
])
def test_status_and_poll_invocations_are_background(argv):
    assert background_invocation(cli._parse_args(argv))


@pytest.mark.parametrize("argv", [
    ["anchor", "me"], ["anchor", "me", "--json"], ["crew"], ["crew", "--json"],
    ["inbox"], ["go", "aegis-1", "me"], ["work", "item", "show", "aegis-1"],
])
def test_interactive_invocations_are_not_background(argv):
    assert not background_invocation(cli._parse_args(argv))


def test_main_runs_a_status_segment_inside_the_background_context(monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "_main", lambda a, argv=None: seen.append(read_priority()) or 0)
    cli.main(["crew", "--count"])
    cli.main(["anchor", "me"])
    assert seen == ["background", None]
    assert read_priority() is None  # nothing leaks past the invocation


def test_background_read_carries_the_header_and_a_normal_read_does_not(wire):
    registry()._query("SELECT * WHERE {}")
    with background_reads():
        registry()._query("SELECT * WHERE {}")
    assert wire.priorities() == [None, "background"]


def test_background_never_reaches_a_write(wire, monkeypatch):
    from shantytown import quipu_auth
    monkeypatch.setattr(quipu_auth, "write_headers",
                        lambda server: {"Content-Type": "application/json"})
    wire.answer = lambda request: {"conforms": True, "tx_id": 1}
    with background_reads():
        try:
            registry()._knot("<urn:a> <urn:b> <urn:c> .")
        except Exception:
            pass  # only the outgoing request matters here
    assert wire.requests and wire.priorities() == [None]


@pytest.mark.parametrize("code", [408, 429, 503])
def test_a_shed_background_read_is_unknown_with_its_retry_time(wire, code):
    wire.answer = lambda request: busy(code, "7")
    with background_reads(), pytest.raises(CouldNotLook, match="retry after 7s"):
        registry().all()
    # ...and the next background read does not touch the network at all.
    with background_reads(), pytest.raises(CouldNotLook, match="quipu busy"):
        registry().all()
    assert len(wire.requests) == 1


def test_a_recorded_busy_window_never_blocks_a_normal_read(wire):
    quipu_busy.record(SERVER, 30)
    assert registry()._query("SELECT * WHERE {}") == []
    assert len(wire.requests) == 1


def test_a_query_rejection_is_still_a_rejection(wire):
    wire.answer = lambda request: HTTPError(SERVER + "/query", 400, "bad", Message(),
                                            io.BytesIO(b'{"error": "unsupported"}'))
    with pytest.raises(quipu.QuipuQueryRejected):
        registry()._query("SELECT * WHERE {}")
