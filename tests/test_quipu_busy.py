"""aegis-jve: busy answers make background st reads back off; normal reads are never blocked."""
import io
from email.message import Message
from urllib.error import HTTPError

import pytest

from shantytown import quipu_busy, seeds_read_cache
from shantytown.query_identity import read_context, read_headers

SERVER = "http://quipu.example"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("ST_SEEDS_READ_CACHE", "0")  # isolate from the exact cache
    monkeypatch.delenv("QUIPU_PRIORITY", raising=False)


def busy_error(code, retry_after=None):
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return HTTPError(SERVER + "/query", code, "busy", headers, io.BytesIO(b"{}"))


def read(fetch):
    return seeds_read_cache.read(SERVER, "SELECT * WHERE {}", 5,
                                 opener=None, fetch=fetch, validate=lambda r: r)


def failing(error):
    def fetch():
        raise error
    return fetch


@pytest.mark.parametrize("code", [408, 429, 503])
def test_busy_answer_makes_background_reads_skip_the_network(code, monkeypatch):
    with pytest.raises(HTTPError):
        read(failing(busy_error(code, retry_after=7)))
    assert 6 < quipu_busy.remaining(SERVER) <= 7
    monkeypatch.setenv("QUIPU_PRIORITY", "background")
    calls = []
    with pytest.raises(quipu_busy.QuipuBusy, match="quipu busy"):
        read(lambda: calls.append(1) or {"rows": []})
    assert calls == [], "background read never touched the network"


def test_normal_reads_are_never_blocked_by_the_signal():
    with pytest.raises(HTTPError):
        read(failing(busy_error(503, retry_after=20)))
    assert read(lambda: {"ok": True}) == {"ok": True}


def test_background_reads_proceed_when_not_busy(monkeypatch):
    monkeypatch.setenv("QUIPU_PRIORITY", "background")
    assert read(lambda: {"ok": True}) == {"ok": True}


@pytest.mark.parametrize("code", [400, 404, 500, 422])
def test_non_busy_errors_record_nothing(code):
    with pytest.raises(HTTPError):
        read(failing(busy_error(code, retry_after=7)))
    assert quipu_busy.remaining(SERVER) == 0


@pytest.mark.parametrize("value,expected", [(None, 5), ("7", 7), ("0", 1), ("999", 30), ("soon", 5)])
def test_retry_after_is_honoured_and_clamped(value, expected):
    assert quipu_busy.retry_after_seconds(value) == expected


def test_signal_expires():
    quipu_busy.record(SERVER, "2", now=1000.0)
    assert quipu_busy.remaining(SERVER, now=1001.0) == pytest.approx(1.0)
    assert quipu_busy.remaining(SERVER, now=1003.0) == 0


def test_busy_file_is_private():
    quipu_busy.record(SERVER, "3")
    path = quipu_busy._path(SERVER)
    assert path.stat().st_mode & 0o077 == 0
    assert path.parent.stat().st_mode & 0o077 == 0


@pytest.mark.parametrize("value,sent", [
    ("background", "background"), ("BACKGROUND", "background"),
    ("high", None), ("normal", None), ("", None), (None, None),
])
def test_priority_header_only_ever_lowers(value, sent, monkeypatch):
    if value is not None:
        monkeypatch.setenv("QUIPU_PRIORITY", value)
    assert read_context().get("QUIPU_PRIORITY") == sent
    assert read_headers().get("X-Quipu-Priority") == sent


def test_busy_error_is_a_timeout_so_callers_treat_it_as_transient():
    assert issubclass(quipu_busy.QuipuBusy, TimeoutError)
