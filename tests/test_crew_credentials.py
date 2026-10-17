"""Private synthetic launch/fallback tests; no real credentials or service calls."""
import hashlib
import json
import os
from pathlib import Path
import stat

import pytest

from shantytown import crew_credentials as C
from shantytown import provision as P


@pytest.fixture
def configured(tmp_path, monkeypatch):
    root = tmp_path / "root"
    provision = root / "provision"
    provision.mkdir(parents=True)
    principal = "urn:crew:alice"
    token = "synthetic-named"
    ref = dict(audience="homelab-mcp", project="fixture", path="/mcp-crew/alice",
               key="CREW_" + hashlib.sha256(principal.encode()).hexdigest()[:24].upper() + "_HOMELAB_MCP",
               secret_id="exact-id", secret_version=1,
               token_sha256=hashlib.sha256(token.encode()).hexdigest(),
               shared_key="SHARED_TOKEN")
    config = dict(version=1, enabled=True, server="http://example.invalid",
                  agents={"alice": dict(principal=principal, servers={"probe": ref})})
    path = provision / "crew-credentials.json"
    path.write_text(json.dumps(config))
    path.chmod(0o600)
    (provision / "secrets.env").write_text("SHARED_TOKEN=synthetic-shared\n")
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    monkeypatch.setattr(C, "_directory", lambda agent: runtime)
    servers = {"probe": {"type": "http", "url": "http://example.invalid/mcp",
                         "headers": {"Authorization": "Bearer synthetic-shared",
                                     "X-Control": "positive"}}}
    return root, config, path, runtime, servers, token


def test_materialize_then_helper_and_deleted_file_shared_fallback(configured):
    root, config, path, runtime, servers, token = configured
    before = dict(os.environ)
    calls = []
    def fetch(data, ref):
        calls.append(ref["secret_id"])
        return token
    result = C.project(servers, root, "alice", "codex", fetch=fetch)
    assert calls == ["exact-id"]
    assert (runtime / "probe").read_text() == token
    assert stat.S_IMODE((runtime / "probe").stat().st_mode) == 0o600
    assert result["probe"]["headers"] == {"X-Control": "positive"}
    assert "headersHelper" in result["probe"]
    native = P._codex_servers(result)["probe"]
    assert native["http_headers_helper"] == result["probe"]["headersHelper"]
    assert token not in json.dumps(result) and "synthetic-shared" not in json.dumps(result)
    assert C.headers(root, "alice", "probe") == {"Authorization": "Bearer " + token}
    (runtime / "probe").unlink()
    assert C.headers(root, "alice", "probe") == {"Authorization": "Bearer synthetic-shared"}
    assert dict(os.environ) == before
    assert servers["probe"]["headers"]["Authorization"] == "Bearer synthetic-shared"


def test_failed_fetch_removes_previous_launch_value_no_retry(configured):
    root, _, _, runtime, servers, token = configured
    (runtime / "probe").write_text(token)
    calls = []
    def fail(*args):
        calls.append(1)
        raise RuntimeError("do-not-print-response")
    with pytest.warns(RuntimeWarning, match="shared fallback") as caught:
        C.project(servers, root, "alice", "claude", fetch=fail)
    assert calls == [1] and not (runtime / "probe").exists()
    assert "do-not-print" not in str(caught[0].message)
    assert C.headers(root, "alice", "probe")["Authorization"] == "Bearer synthetic-shared"


def test_default_off_and_unselected_agent_do_nothing(configured):
    root, data, path, runtime, servers, _ = configured
    assert C.project(servers, root, "bob", "codex") is servers
    data["enabled"] = False
    path.write_text(json.dumps(data))
    assert C.project(servers, root, "alice", "codex") is servers
    assert list(runtime.iterdir()) == []


def test_readonly_expected_projection_never_fetches_or_materializes(configured):
    root, _, _, runtime, servers, _ = configured
    got = C.project(servers, root, "alice", "codex", materialize=False,
                    fetch=lambda *args: pytest.fail("network during drift read"))
    assert "headersHelper" in got["probe"]
    assert list(runtime.iterdir()) == []


@pytest.mark.parametrize("change", [
    {"path": "/mcp-crew/bob"}, {"audience": "agent"},
    {"key": "FOREIGN"}, {"secret_version": True},
    {"shared_key": "../other"}, {"token_sha256": "wrong"},
])
def test_foreign_or_malformed_reference_refused(configured, change):
    root, data, path, _, servers, _ = configured
    data["agents"]["alice"]["servers"]["probe"].update(change)
    path.write_text(json.dumps(data))
    with pytest.raises(C.Unavailable):
        C.project(servers, root, "alice", "codex")


def test_runtime_tamper_and_symlink_fall_back_without_reading_target(configured, tmp_path):
    root, _, _, runtime, _, _ = configured
    foreign = tmp_path / "foreign"
    foreign.write_text("foreign-token")
    foreign.chmod(0o600)
    (runtime / "probe").symlink_to(foreign)
    assert C.headers(root, "alice", "probe")["Authorization"] == "Bearer synthetic-shared"
    assert foreign.read_text() == "foreign-token"


def test_wrong_hash_is_not_materialized(configured):
    root, _, _, runtime, servers, _ = configured
    with pytest.warns(RuntimeWarning):
        C.project(servers, root, "alice", "codex", fetch=lambda *a: "wrong-token")
    assert not (runtime / "probe").exists()


def test_private_config_symlink_refused(configured, tmp_path):
    root, _, path, _, _, _ = configured
    retained = tmp_path / "retained.json"
    path.rename(retained)
    path.symlink_to(retained)
    with pytest.raises(OSError):
        C.selection(root, "alice")


def test_absent_configuration_is_default_off(tmp_path):
    assert C.selection(tmp_path, "alice") is None


def test_unavailable_shared_provider_does_not_emit_empty_auth(configured):
    root, _, _, _, _, _ = configured
    (root / "provision" / "secrets.env").unlink()
    with pytest.raises(C.Unavailable):
        C.headers(root, "alice", "probe")


def test_actual_provision_writes_helper_only(configured, monkeypatch, tmp_path):
    from shantytown.protocols import Agent
    root, _, _, runtime, servers, token = configured
    d = root / "provision"
    (d / P.MCP_TEMPLATE).write_text(json.dumps({"mcpServers": servers}))
    (d / P.CONSENT_TEMPLATE).write_text("{}")
    ws = tmp_path / "workspace"
    ws.mkdir()
    monkeypatch.setattr(C, "_fetch", lambda *args: token)
    got = P.provision(Agent(name="alice", workspace=str(ws)), root)
    assert got == ["probe"]
    persistent = (ws / ".mcp.json").read_text()
    assert token not in persistent and "synthetic-shared" not in persistent
    assert "headersHelper" in json.loads(persistent)["mcpServers"]["probe"]
    assert (runtime / "probe").read_text() == token


def test_boolean_version_is_not_an_integer(configured):
    root, data, path, _, _, _ = configured
    data["version"] = True
    path.write_text(json.dumps(data))
    with pytest.raises(C.Unavailable):
        C.selection(root, "alice")


def test_runtime_directory_rejects_non_tmpfs_and_symlink(tmp_path, monkeypatch):
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    real = C.__dict__["_directory"]
    monkeypatch.setattr(C, "_tmpfs", lambda path: False)
    with pytest.raises(C.Unavailable, match="tmpfs"):
        real("alice", base=base)
    monkeypatch.setattr(C, "_tmpfs", lambda path: True)
    parent = base / "shantytown-credentials"
    parent.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(C.Unavailable, match="directory"):
        real("alice", base=base)
    assert not (tmp_path / "alice").exists()


def test_real_http_fetch_pins_value_and_never_follows_redirect(configured, tmp_path, monkeypatch):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    root, data, _, _, _, token = configured
    ref = data["agents"]["alice"]["servers"]["probe"]
    home = tmp_path / "home"
    (home / ".infisical").mkdir(parents=True)
    bootstrap = home / ".infisical" / "credentials"
    bootstrap.write_text("INFISICAL_CLIENT_ID=fixture-id\nINFISICAL_CLIENT_SECRET=fixture-secret\n")
    bootstrap.chmod(0o600)
    monkeypatch.setenv("HOME", str(home))
    calls = []
    class Handler(BaseHTTPRequestHandler):
        redirect = False
        def log_message(self, *args):
            pass
        def do_POST(self):
            calls.append(("login", self.path))
            assert self.path == "/api/v1/auth/universal-auth/login"
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert body == {"clientId": "fixture-id", "clientSecret": "fixture-secret"}
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"accessToken": "fixture-auth"}).encode())
        def do_GET(self):
            calls.append(("secret", self.path))
            if self.redirect:
                self.send_response(302)
                self.send_header("Location", "/must-not-follow")
                self.end_headers()
                return
            assert self.headers["Authorization"] == "Bearer fixture-auth"
            assert "/v3/secrets/raw/" + ref["key"] + "?" in self.path
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"secret": {
                "_id": "exact-id", "version": 1, "secretValue": token}}).encode())
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    data["server"] = "http://127.0.0.1:" + str(server.server_port)
    try:
        assert C._fetch(data, ref) == token
        assert len(calls) == 2
        Handler.redirect = True
        with pytest.raises(Exception):
            C._fetch(data, ref)
        assert len(calls) == 4
        assert all("/must-not-follow" not in path for _, path in calls)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
