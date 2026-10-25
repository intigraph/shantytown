"""Actual local HTTP controls; synthetic credentials and no production traffic."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest

from shantytown import crew_rules

BODY = json.dumps({"rows": [], "count": 0, "truncated": False}).encode()


@pytest.fixture
def endpoint(tmp_path, monkeypatch):
    running = []
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    monkeypatch.setattr(crew_rules, "request_headers", lambda: {
        "Content-Type": "application/json", "Authorization": "Bearer fixture-only"})

    def start(mode, body=BODY):
        state = SimpleNamespace(started=threading.Event(), finished=threading.Event(),
                                release=threading.Event(), headers=None)

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                state.headers = dict(self.headers)
                state.started.set()
                try:
                    if mode == "slow_headers":
                        header = (b"HTTP/1.0 200 OK\r\nContent-Length: "
                                  + str(len(body)).encode() + b"\r\n\r\n")
                        for byte in header:
                            self.connection.sendall(bytes([byte]))
                            if state.release.wait(.01):
                                return
                    else:
                        if mode == "stall_headers":
                            state.release.wait(2)
                        self.send_response(200)
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                    if mode == "stall_body":
                        state.release.wait(2)
                    if mode == "slow_body":
                        for byte in body:
                            self.wfile.write(bytes([byte]))
                            self.wfile.flush()
                            if state.release.wait(.01):
                                return
                    else:
                        self.wfile.write(body)
                        self.wfile.flush()
                except OSError:
                    pass  # Expiry closes the child's socket.
                finally:
                    state.finished.set()

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01))
        thread.start()
        running.append((state, server, thread))
        (tmp_path / "shantytown.toml").write_text(
            '[env]\nQUIPU_SERVER="http://127.0.0.1:' + str(server.server_port) + '"\n')
        return state

    yield start
    for state, server, thread in running:
        state.release.set()
        server.shutdown()
        thread.join(2)
        server.server_close()
        assert not thread.is_alive()
        if state.started.is_set():
            assert state.finished.wait(2)


def test_ordinary_response_preserves_attribution_and_json(tmp_path, endpoint):
    state = endpoint("ordinary")
    assert crew_rules.ask(tmp_path, "fixture", {}, timeout=2) == []
    assert state.headers["X-Quipu-Client"] == "st"
    assert state.headers["Authorization"] == "Bearer fixture-only"


@pytest.mark.parametrize("mode", ["slow_body", "slow_headers"])
def test_slow_progress_cannot_extend_total_deadline(tmp_path, endpoint, mode):
    state = endpoint(mode)
    budget = .2
    start = time.monotonic()
    with pytest.raises(TimeoutError):
        crew_rules.ask(tmp_path, "fixture", {}, timeout=budget)
    elapsed = time.monotonic() - start
    assert state.started.is_set(), "the progressing peer was actually contacted"
    assert elapsed < budget + .45  # Includes process teardown and CI scheduling.
    print(f"{mode}: deadline={budget:.3f}s; refused after {elapsed:.3f}s")


@pytest.mark.parametrize("mode", ["stall_body", "stall_headers"])
def test_stalled_response_is_bounded_too(tmp_path, endpoint, mode):
    endpoint(mode)
    start = time.monotonic()
    with pytest.raises(TimeoutError):
        crew_rules.ask(tmp_path, "fixture", {}, timeout=.2)
    assert time.monotonic() - start < .65


def test_response_cap_survives_transport_change(tmp_path, endpoint):
    endpoint("ordinary", b"x" * (crew_rules.MAX_BYTES + 2))
    with pytest.raises(ValueError, match="byte cap"):
        crew_rules.ask(tmp_path, "fixture", {}, timeout=2)


def test_expired_network_child_is_already_reaped(tmp_path, endpoint, monkeypatch):
    from shantytown import _deadline_http
    original = _deadline_http.subprocess.Popen
    children = []

    def spawn(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(_deadline_http.subprocess, "Popen", spawn)
    endpoint("stall_body")
    with pytest.raises(TimeoutError):
        crew_rules.ask(tmp_path, "fixture", {}, timeout=.2)
    assert len(children) == 1
    assert children[0].returncode is not None


def test_credentials_and_url_use_private_stdin_not_arguments(monkeypatch):
    from shantytown import _deadline_http
    calls = []

    class Child:
        returncode = 0

        def __init__(self, command, **kwargs):
            calls.append((command, kwargs))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def communicate(self, **kwargs):
            calls[0][1].update(kwargs)
            return b"{}", None

    monkeypatch.setattr(_deadline_http.subprocess, "Popen", Child)
    assert _deadline_http.post("https://graph.example/ask", "{}",
                               {"Authorization": "Bearer fixture-only"},
                               timeout=2, max_bytes=512) == b"{}"
    command, options = calls[0]
    assert "fixture-only" not in repr(command) and "graph.example" not in repr(command)
    assert command[1:3] == ["-I", "-S"]
    packet = json.loads(options["input"])
    assert packet["headers"]["Authorization"] == "Bearer fixture-only"
    assert options["stdin"] == options["stdout"] == subprocess.PIPE
    assert options["stderr"] == subprocess.DEVNULL
    assert 0 < options["timeout"] <= 2


@pytest.mark.parametrize("budget", [0, -1, float("inf"), float("nan"), True])
def test_invalid_budget_refuses_before_child(budget, monkeypatch):
    from shantytown import _deadline_http
    monkeypatch.setattr(_deadline_http.subprocess, "Popen",
                        lambda *a, **k: pytest.fail("invalid budget launched a child"))
    with pytest.raises(ValueError):
        _deadline_http.post("https://graph.example/ask", "{}", {},
                            timeout=budget, max_bytes=512)


def test_helper_startup_consumes_the_same_deadline(monkeypatch):
    from shantytown import _deadline_http
    clock = SimpleNamespace(now=0, killed=False, reaped=False)
    monkeypatch.setattr(_deadline_http, "time", SimpleNamespace(monotonic=lambda: clock.now))

    class Child:
        def __init__(self, *args, **kwargs):
            clock.now = .3  # Launch itself exceeded the .2-second budget.

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def kill(self):
            clock.killed = True

        def communicate(self, **kwargs):
            assert clock.killed and not kwargs
            clock.reaped = True
            return b"", None

    monkeypatch.setattr(_deadline_http.subprocess, "Popen", Child)
    with pytest.raises(TimeoutError):
        _deadline_http.post("https://graph.example/ask", "{}", {},
                            timeout=.2, max_bytes=512)
    assert clock.killed and clock.reaped
