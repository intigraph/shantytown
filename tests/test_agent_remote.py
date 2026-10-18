"""Pairing failures must refuse without lifecycle actions or response leakage."""
import base64
import hashlib
import json
import os
import socket
import struct
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from shantytown import agent_remote as remote, cli, codex_daemon, codex_shells
from shantytown.protocols import Agent, Answer


class Registry:
    def get(self, name):
        assert name == "alice"
        return Agent(name, harness="codex")

    def all(self):
        return Answer([Agent("alice", harness="codex"), Agent("bob", harness="claude")], "fixture", True)


class Provider:
    calls = []
    reply = {"environmentId": "private-env", "manualPairingCode": "TEST-ONLY",
             "expiresAt": 4102444800, "pairingCode": "UNPRINTABLE-SECRET"}

    def __init__(self, agent, timeout):
        assert agent == "alice"
        self.calls.append((agent, timeout))

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def rpc(self, method, params):
        if method == "remoteControl/status/read":
            return {"status": "connected", "serverName": "host", "environmentId": "private-env"}
        assert method == "remoteControl/pairing/start" and params == {"manualCode": True}
        return self.reply


def args(action="pair", **extra):
    return SimpleNamespace(remote_action=action, agent="alice", json=True, timeout=1, **extra)


def test_explicit_agent_pair_is_filtered_and_not_persisted(capsys):
    assert remote.run(args(), Registry(), control_factory=Provider) == 0
    output = capsys.readouterr().out
    row = json.loads(output)
    assert row["agent"] == "alice" and row["manual_pairing_code"] == "TEST-ONLY"
    assert row["expires_at"] == "2100-01-01T00:00:00+00:00"
    assert "private-env" not in output and "UNPRINTABLE-SECRET" not in output


def test_dry_run_never_requests_a_code(capsys):
    class ReadOnly(Provider):
        def rpc(self, method, params):
            assert method == "remoteControl/status/read"
            return super().rpc(method, params)
    a = args()
    a.dry_run = True
    assert remote.run(a, Registry(), control_factory=ReadOnly) == 0
    row = json.loads(capsys.readouterr().out)
    assert row["action"] == "would_pair" and "manual_pairing_code" not in row


def test_wrong_registry_identity_never_connects(capsys):
    class Wrong(Registry):
        def get(self, name):
            return Agent("bob", harness="codex")
    def forbidden(*_):
        pytest.fail("connected to wrong agent")
    assert remote.run(args(), Wrong(), control_factory=forbidden) == 2
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("host", [None, "other-host"])
def test_host_assigned_card_never_uses_foreign_or_unresolved_deployment(host, monkeypatch, capsys):
    class Assigned(Registry):
        def get(self, name):
            return Agent(name, harness="codex", host="selected-host")

        def all(self):
            return Answer([self.get("alice")], "fixture", True)
    monkeypatch.setattr(remote, "local_host", lambda _: host)
    def forbidden(*_):
        pytest.fail("connected without local host binding")
    assert remote.run(args(), Assigned(), control_factory=forbidden) == 2
    assert capsys.readouterr().out == ""
    assert remote.run(args("list"), Assigned(), control_factory=forbidden) == 0
    row, = json.loads(capsys.readouterr().out)
    assert row["host"] == "selected-host" and row["availability"] == "unavailable"


def test_host_assigned_card_uses_matching_deployment(monkeypatch, capsys):
    class Assigned(Registry):
        def get(self, name):
            return Agent(name, harness="codex", host="selected-host")
    monkeypatch.setattr(remote, "local_host", lambda _: "selected-host")
    assert remote.run(args(), Assigned(), control_factory=Provider) == 0
    assert json.loads(capsys.readouterr().out)["host"] == "selected-host"


def test_generation_change_withholds_pair_output(capsys):
    class Changed(Provider):
        def __exit__(self, *_):
            raise remote.RemoteError("daemon identity changed; response withheld")
    assert remote.run(args(), Registry(), control_factory=Changed) == 2
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("state", ["disabled", "connecting", "errored", {}, None])
def test_disconnected_or_malformed_status_never_pairs(state, capsys):
    class Disconnected(Provider):
        def rpc(self, method, params):
            assert method == "remoteControl/status/read"
            return {"status": state, "serverName": "host"}
    assert remote.run(args(), Registry(), control_factory=Disconnected) == 2
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("reply", [
    {}, {"environmentId": "wrong", "manualPairingCode": "MUST-NOT-PRINT"},
    {"environmentId": "private-env", "manualPairingCode": "MUST-NOT-PRINT", "expiresAt": 1},
    {"environmentId": "private-env", "manualPairingCode": "MUST-NOT-PRINT", "expiresAt": True},
    {"environmentId": "private-env", "manualPairingCode": "\nsecret", "expiresAt": 4102444800},
])
def test_malformed_expired_and_wrong_environment_withheld(reply, monkeypatch, capsys):
    monkeypatch.setattr(Provider, "reply", reply)
    assert remote.run(args(), Registry(), control_factory=Provider) == 2
    output = capsys.readouterr()
    assert output.out == "" and "MUST-NOT-PRINT" not in output.err


@pytest.mark.parametrize("error", [TimeoutError("secret"), PermissionError("secret"), ValueError("secret")])
def test_provider_failure_never_echoed_or_retried(error, capsys):
    calls = []
    def fail(*_):
        calls.append(1)
        raise error
    assert remote.run(args(), Registry(), control_factory=fail) == 2
    output = capsys.readouterr()
    assert output.out == "" and "secret" not in output.err and len(calls) == 1


def test_discovery_distinguishes_inactive_and_unsupported(capsys):
    def missing(*_):
        raise remote.Inactive("no socket")
    assert remote.run(args("list"), Registry(), control_factory=missing) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [r["availability"] for r in rows] == ["inactive", "unavailable"]


def test_missing_runtime_does_not_create_or_launch(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    with pytest.raises(remote.Inactive):
        with remote.Control("alice", 0.1):
            pytest.fail("missing daemon accepted")
    assert not list(tmp_path.iterdir())


def test_runtime_resolution_and_traversal(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert codex_daemon.runtime_home("alice") == tmp_path / "shantytown/codex/alice"
    for invalid in ["../bob", "/bob", "..", ""]:
        with pytest.raises(ValueError):
            codex_daemon.runtime_home(invalid)


def test_normal_parser_requires_explicit_target():
    assert cli._parse_args(["agent", "remote", "list", "--json"]).cmd == "remote"
    assert cli._parse_args(["agent", "remote", "pair", "alice"]).agent == "alice"
    with pytest.raises(SystemExit):
        cli._parse_args(["agent", "remote", "pair"])


@pytest.fixture
def wire(monkeypatch):
    # Short path avoids UNIX SUN_LEN; no real daemon, registry or HOME is used.
    with tempfile.TemporaryDirectory(prefix="st-remote-", dir="/tmp") as directory:
        home = Path(directory)
        (home / "app-server-control").mkdir()
        (home / "app-server-daemon").mkdir()
        (home / "app-server-daemon/app-server.pid").write_text(json.dumps({'pid': os.getpid()}))
        path = home / "app-server-control/app-server-control.sock"
        listener = socket.socket(socket.AF_UNIX)
        listener.bind(str(path))
        listener.listen(1)
        listener.settimeout(2)
        monkeypatch.setattr(codex_daemon, "runtime_home", lambda _: home)
        monkeypatch.setattr(codex_shells, "control_binding", lambda _: dict(pid=os.getpid(), endpoint=str(path)))
        yield listener
        listener.close()


def test_wrong_socket_peer_refused_before_protocol(wire, monkeypatch):
    monkeypatch.setattr(codex_shells, "control_binding", lambda _: dict(pid=os.getpid()+1, endpoint=wire.getsockname()))
    with pytest.raises(ValueError, match="foreign RPC peer"):
        with remote.Control("alice", 0.5):
            pytest.fail("wrong daemon accepted")


def test_unresponsive_socket_is_bounded(wire):
    # A listener exists with a proven peer, but it sends no handshake response.
    with pytest.raises(TimeoutError):
        with remote.Control("alice", 0.05):
            pytest.fail("unresponsive daemon accepted")


def test_real_unix_websocket_status_transport(wire):
    requests = []
    errors = []
    def server():
        try:
            conn, _ = wire.accept()
            with conn:
                conn.settimeout(2)
                head = b""
                while not head.endswith(b"\r\n\r\n"):
                    head += conn.recv(1)
                key = next(l.split(b":", 1)[1].strip() for l in head.split(b"\r\n") if l.startswith(b"Sec-WebSocket-Key:"))
                accept = base64.b64encode(hashlib.sha1(key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest())
                conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: " + accept + b"\r\n\r\n")
                def read(n):
                    value = b""
                    while len(value) < n:
                        value += conn.recv(n - len(value))
                    return value
                for _ in range(3):
                    first, second = read(2)
                    assert first == 0x81 and second & 128
                    size = second & 127
                    if size == 126:
                        size = struct.unpack("!H", read(2))[0]
                    mask = read(4)
                    payload = json.loads(bytes(b ^ mask[i % 4] for i, b in enumerate(read(size))))
                    requests.append(payload["method"])
                    if "id" not in payload:
                        continue
                    result = {} if payload["method"] == "initialize" else {"status": "connected", "serverName": "host"}
                    data = json.dumps({"id": payload["id"], "result": result}).encode()
                    assert len(data) < 126
                    conn.sendall(bytes([0x81, len(data)]) + data)
        except Exception as e:
            errors.append(e)
    thread = threading.Thread(target=server)
    thread.start()
    with remote.Control("alice", 1) as control:
        assert remote.status(control)["availability"] == "connected"
    thread.join(2)
    assert not thread.is_alive() and not errors
    assert requests == ["initialize", "initialized", "remoteControl/status/read"]
