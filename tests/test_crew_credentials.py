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


def test_named_helper_refuses_shared_codex_role_config_before_fetch(configured, monkeypatch, tmp_path):
    from shantytown.protocols import Agent
    root, _, _, runtime, _, _ = configured
    ws = tmp_path / "workspace"
    ws.mkdir()
    role = root / "settings" / "codex" / "worker"
    role.mkdir(parents=True)
    (role / "config.toml").write_text("")
    monkeypatch.setattr(C, "_fetch", lambda *args: pytest.fail("fetch before identity isolation"))
    # Even explicitly supplied shared secrets cannot bypass the per-agent guard.
    with pytest.raises(P.ProvisionError, match="independent per-agent"):
        P.provision(Agent(name="alice", workspace=str(ws), harness="codex"), root, secrets={})
    assert list(runtime.iterdir()) == [] and not (ws / ".mcp.json").exists()


def test_actual_codex_provision_keeps_named_helper_in_independent_agent_config(configured, monkeypatch, tmp_path):
    import tomllib
    from shantytown.protocols import Agent
    root, _, _, runtime, servers, token = configured
    d = root / "provision"
    (d / P.MCP_TEMPLATE).write_text(json.dumps({"mcpServers": servers}))
    ws = tmp_path / "workspace"
    ws.mkdir()
    settings = root / "settings" / "codex"
    role = settings / "worker"
    role.mkdir(parents=True)
    (role / "config.toml").write_text('model = "role-fixture"\n')
    agent = settings / "agent-alice"
    agent.mkdir()
    config = agent / "config.toml"
    config.write_text('model = "agent-fixture"\n')
    old_role = (role / "config.toml").read_bytes()
    monkeypatch.setattr(C, "_fetch", lambda *args: token)
    P.provision(Agent(name="alice", workspace=str(ws), harness="codex"), root,
                settings_path=str(config))
    got = tomllib.loads(config.read_text())["mcp_servers"]["probe"]
    assert "http_headers_helper" in got
    assert "Authorization" not in got.get("http_headers", {})
    assert token not in config.read_text()
    assert (role / "config.toml").read_bytes() == old_role
    assert (runtime / "probe").read_text() == token


def test_cli_file_handoff_and_next_request_shared_fallback(configured, monkeypatch):
    from shantytown import quipu_auth
    root, data, path, runtime, servers, token = configured
    ref = dict(data["agents"]["alice"]["servers"]["probe"])
    cli_value = "synthetic-quipu-only"
    ref.update(audience="quipu", key=ref["key"].removesuffix("_HOMELAB_MCP") + "_QUIPU",
               token_sha256=hashlib.sha256(cli_value.encode()).hexdigest())
    data["agents"]["alice"]["quipu_cli"] = ref
    path.write_text(json.dumps(data))
    C.project(servers, root, "alice", "codex", fetch=lambda data, ref: cli_value if ref["audience"] == "quipu" else token)
    env = C.cli_environment(root, "alice")
    assert set(env) == {"QUIPU_AUTH_TOKEN_FILE"}
    assert token not in str(env) and "synthetic-shared" not in str(env)
    monkeypatch.setenv("SHANTY_ROOT", str(root))
    monkeypatch.setenv("SHANTY_AGENT", "alice")
    monkeypatch.setenv("QUIPU_AUTH_TOKEN_FILE", env["QUIPU_AUTH_TOKEN_FILE"])
    monkeypatch.delenv("QUIPU_AUTH_TOKEN", raising=False)
    assert quipu_auth.token() == cli_value
    (runtime / "quipu-cli").unlink()
    assert quipu_auth.token() == "synthetic-shared"
    monkeypatch.setenv("QUIPU_AUTH_TOKEN", "explicit-fixture-override")
    assert quipu_auth.token() == "explicit-fixture-override"


def test_launcher_carries_only_cli_file_path_to_both_harnesses(configured, monkeypatch):
    from shantytown import harness, runtime as runtime_mod
    from shantytown.protocols import Agent
    root, data, path, _, _, token = configured
    ref = dict(data["agents"]["alice"]["servers"]["probe"])
    cli_value = "synthetic-quipu-only"
    ref.update(audience="quipu", key=ref["key"].removesuffix("_HOMELAB_MCP") + "_QUIPU",
               token_sha256=hashlib.sha256(cli_value.encode()).hexdigest())
    data["agents"]["alice"]["quipu_cli"] = ref
    path.write_text(json.dumps(data))
    monkeypatch.setattr(runtime_mod, "_settings_env", lambda *a: {"QUIPU_AUTH_TOKEN": "synthetic-parent-secret"})
    monkeypatch.setattr(harness, "resolve_model", lambda *a: None)
    for name, config in [("claude", "settings.json"), ("codex", "config.toml")]:
        card = Agent(name="alice", harness=name)
        launch = harness.get(name).launch(card, str(root / config), root)
        assert "-u QUIPU_AUTH_TOKEN " in launch
        assert "QUIPU_AUTH_TOKEN_FILE=/run/user/" in launch
        assert token not in launch and "synthetic-parent-secret" not in launch


def test_missing_optin_does_not_restrict_existing_card_names(tmp_path):
    assert C.selection(tmp_path, "worker.legacy") is None


def test_repeated_server_reference_fetches_once_per_launch(configured):
    root, data, path, _, servers, token = configured
    data["agents"]["alice"]["servers"]["second"] = dict(data["agents"]["alice"]["servers"]["probe"])
    path.write_text(json.dumps(data))
    servers["second"] = dict(servers["probe"])
    calls = []
    def fetch(*args):
        calls.append(1)
        return token
    C.project(servers, root, "alice", "codex", fetch=fetch)
    assert calls == [1]


@pytest.mark.parametrize("conflict", ["pin", "audience"])
def test_conflicting_audience_references_refuse_before_fetch(configured, conflict):
    root, data, path, _, servers, _ = configured
    ref = dict(data["agents"]["alice"]["servers"]["probe"])
    if conflict == "pin":
        ref["secret_version"] += 1
        data["agents"]["alice"]["servers"]["second"] = ref
        servers["second"] = dict(servers["probe"])
    else:
        ref.update(audience="quipu", key=ref["key"].removesuffix("_HOMELAB_MCP") + "_QUIPU")
        data["agents"]["alice"]["quipu_cli"] = ref
    path.write_text(json.dumps(data))
    with pytest.raises(C.Unavailable):
        C.project(servers, root, "alice", "codex", fetch=lambda *a: pytest.fail("must not fetch"))


@pytest.mark.parametrize('child', ['alice', 'carol'])
@pytest.mark.parametrize('kind,settings', [('claude', 'settings.json'), ('codex', 'config.toml')])
def test_child_launch_clears_foreign_managed_cli_path(configured, monkeypatch, child, kind, settings):
    import subprocess
    import sys
    from shantytown import harness, runtime as runtime_mod
    from shantytown.protocols import Agent
    root, _, _, _, _, _ = configured
    foreign = f'/run/user/{os.getuid()}/shantytown-credentials/bob/quipu-cli'
    monkeypatch.setenv('QUIPU_AUTH_TOKEN_FILE', foreign)
    monkeypatch.setattr(runtime_mod, '_settings_env', lambda *a: {})
    monkeypatch.setattr(harness, 'resolve_model', lambda *a: None)
    card = Agent(name=child, harness=kind)
    launch = harness.get(kind).launch(card, str(root / settings), root)
    assert '-u QUIPU_AUTH_TOKEN_FILE ' in launch
    assert foreign not in launch
    options, values = harness._crew_launch_identity(card, root)
    assert values == ''
    # Execute the actual shared env boundary privately; no native harness starts.
    import shlex
    result = subprocess.run(['bash', '-c', 'env ' + options + shlex.quote(sys.executable)
        + ' -c ' + shlex.quote('import os; assert "QUIPU_AUTH_TOKEN_FILE" not in os.environ')],
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('agent', ['alice', 'carol', None])
@pytest.mark.parametrize('suffix', ['bob/quipu-cli', 'alice/../bob/quipu-cli'])
def test_foreign_managed_file_never_reaches_generic_reader(configured, monkeypatch, agent, suffix):
    from shantytown import quipu_auth
    root, _, _, _, _, _ = configured
    monkeypatch.setenv('SHANTY_ROOT', str(root))
    if agent:
        monkeypatch.setenv('SHANTY_AGENT', agent)
    else:
        monkeypatch.delenv('SHANTY_AGENT', raising=False)
    monkeypatch.delenv('QUIPU_AUTH_TOKEN', raising=False)
    monkeypatch.setenv('QUIPU_AUTH_TOKEN_FILE',
        f'/run/user/{os.getuid()}/shantytown-credentials/{suffix}')
    with pytest.raises(C.Unavailable):
        quipu_auth.token()
    monkeypatch.setenv('QUIPU_AUTH_TOKEN', 'explicit-invocation')
    assert quipu_auth.token() == 'explicit-invocation'


def test_global_cli_file_provider_remains_compatible(configured, monkeypatch):
    from shantytown import harness, quipu_auth, runtime as runtime_mod
    from shantytown.protocols import Agent
    root, _, _, _, _, _ = configured
    global_file = root / 'global-token'
    global_file.write_text('synthetic-global-provider')
    monkeypatch.setenv('QUIPU_AUTH_TOKEN_FILE', str(global_file))
    monkeypatch.delenv('QUIPU_AUTH_TOKEN', raising=False)
    monkeypatch.setenv('SHANTY_ROOT', str(root))
    monkeypatch.setenv('SHANTY_AGENT', 'carol')
    assert quipu_auth.token() == 'synthetic-global-provider'
    monkeypatch.setattr(runtime_mod, '_settings_env', lambda *a: {})
    monkeypatch.setattr(harness, 'resolve_model', lambda *a: None)
    for kind, settings in [('claude', 'settings.json'), ('codex', 'config.toml')]:
        launch = harness.get(kind).launch(Agent(name='carol', harness=kind), str(root/settings), root)
        options, values = harness._crew_launch_identity(Agent(name='carol', harness=kind), root)
        import shlex, subprocess, sys
        command = 'env ' + options + shlex.quote(sys.executable) + ' -c ' + shlex.quote(
            'import os; assert os.environ["QUIPU_AUTH_TOKEN_FILE"] == ' + repr(str(global_file)))
        result = subprocess.run(['bash', '-c', command], capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr


def test_inactive_credential_deployment_keeps_legacy_launch_bytes(configured):
    from shantytown import harness
    from shantytown.protocols import Agent
    root, data, path, _, _, _ = configured
    data['enabled'] = False
    path.write_text(json.dumps(data))
    assert harness._crew_launch_identity(Agent(name='carol'), root) == ('', '')
    path.unlink()
    assert harness._crew_launch_identity(Agent(name='carol'), root) == ('', '')
    assert harness._crew_launch_identity(Agent(name='carol'), None) == ('', '')


@pytest.mark.parametrize('kind', ['claude', 'codex'])
def test_own_selected_child_replaces_foreign_parent_path(configured, monkeypatch, kind):
    import shlex, subprocess, sys
    from shantytown import harness
    from shantytown.protocols import Agent
    root, data, path, _, _, _ = configured
    ref = dict(data['agents']['alice']['servers']['probe'])
    ref.update(audience='quipu', key=ref['key'].removesuffix('_HOMELAB_MCP')+'_QUIPU',
               token_sha256=hashlib.sha256(b'synthetic-cli').hexdigest())
    data['agents']['alice']['quipu_cli'] = ref
    path.write_text(json.dumps(data))
    monkeypatch.setenv('QUIPU_AUTH_TOKEN_FILE',
        f'/run/user/{os.getuid()}/shantytown-credentials/bob/quipu-cli')
    monkeypatch.setenv('QUIPU_AUTH_TOKEN', 'synthetic-parent-content')
    options, values = harness._crew_launch_identity(Agent(name='alice', harness=kind), root)
    expected = C.cli_environment(root, 'alice')['QUIPU_AUTH_TOKEN_FILE']
    command = 'env '+options+values+shlex.quote(sys.executable)+' -c '+shlex.quote(
        'import os; assert "QUIPU_AUTH_TOKEN" not in os.environ; '
        'assert os.environ["QUIPU_AUTH_TOKEN_FILE"] == '+repr(expected))
    result = subprocess.run(['bash', '-c', command], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
