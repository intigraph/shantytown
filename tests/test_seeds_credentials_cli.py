"""Opt-in paired-source CLI probe; loopback and inert fixture credentials only.

# arming: agent-invoked cross-repository source qualification; never a live probe
Set SEEDS_ADAPTER_TEST_BINARY to a private candidate, never an installed override.
Ordinary CI still runs the adapter's independent protocol/lifetime unit controls.
"""
import hashlib
import http.server
import json
import os
from pathlib import Path
import subprocess
import threading

import pytest

from shantytown import crew_credentials as C
from shantytown import seeds_credentials as S


@pytest.mark.skipif(not os.environ.get("SEEDS_ADAPTER_TEST_BINARY"),
                    reason="paired native admission candidate not supplied")
def test_actual_native_launcher_before_provider_and_bearer_fixture(tmp_path):
    binary = os.environ["SEEDS_ADAPTER_TEST_BINARY"]
    observed, provider, descriptors = [], [], []
    echo_selected = False

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, data, status=200):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            observed.append((self.path, self.headers.get("Authorization")))
            self.reply({"graphs": []} if self.path == "/graphs" else {"status": "ok"})

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
            observed.append((self.path, self.headers.get("Authorization")))
            if self.path == "/query" and "ASK" in body:
                self.reply({"boolean": False})
            elif self.path == "/query":
                self.reply({"head": {"vars": ["probe"]}, "results": {"bindings": [
                    {"probe": {"type": "literal", "value": "complete"}}
                ] if "SELECT ?probe" in body else []}, "truncated": False})
            else:
                self.reply({"error": self.headers.get("Authorization") if echo_selected else "inert write refusal"}, 403)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        root = tmp_path / "crew"
        (root / "provision").mkdir(parents=True)
        user = tmp_path / "config/seeds"
        user.mkdir(parents=True)
        shared = tmp_path / "shared"
        shared.write_text("shared-inert-fixture")
        (user / "config.toml").write_text(
            f'[quipu]\ntoken_file="{shared}"\ntrusted_hosts=["127.0.0.1"]\n')
        principal = "urn:crew:alice"
        value = "own-inert-fixture"
        ref = dict(audience="quipu", project="fixture", path="/mcp-crew/alice",
                   key="CREW_" + hashlib.sha256(principal.encode()).hexdigest()[:24].upper() + "_QUIPU",
                   secret_id="id", secret_version=1,
                   token_sha256=hashlib.sha256(value.encode()).hexdigest(), shared_key="SHARED")
        config = dict(version=1, enabled=True, agents={
            "alice": dict(principal=principal, servers={}, quipu_cli=ref)})
        selection = root / "provision/crew-credentials.json"
        selection.write_text(json.dumps(config))
        selection.chmod(0o600)
        foreign = tmp_path / "foreign"
        foreign.write_text("foreign-file-inert")
        env = dict(PATH=os.environ["PATH"], HOME=str(tmp_path),
                   XDG_CONFIG_HOME=str(user.parent), SEEDS_QUIPU_TOKEN="foreign-inline-inert",
                   SEEDS_QUIPU_TOKEN_FILE=str(foreign),
                   SEEDS_TOKEN="foreign-inline-inert", QUIPU_AUTH_TOKEN="foreign-inline-inert",
                   QUIPU_AUTH_TOKEN_FILE=str(foreign),
                   SEEDS_QUIPU_CREDENTIAL_PRINCIPAL="foreign-principal",
                   SEEDS_QUIPU_TOKEN_FD="999999",
                   SEEDS_QUIPU_CREDENTIAL_DESTINATION="https://foreign.example")
        original = dict(env)
        operation = ["--graph", "https://example.org/fixture", "create", "fixture", "--json"]

        def runner(command, **kwargs):
            for secret in (value, "shared-inert-fixture", "foreign-inline-inert", "foreign-file-inert"):
                assert secret not in json.dumps(command) + json.dumps(kwargs["env"])
            descriptors.extend(kwargs.get("pass_fds", ()))
            result = subprocess.run(command, **kwargs)
            if not echo_selected:
                for secret in (value, "shared-inert-fixture", "foreign-inline-inert", "foreign-file-inert"):
                    assert secret.encode() not in result.stdout + result.stderr
            return result

        def fetch(*args):
            assert observed == [], "HTTP happened before provider access"
            provider.append(1)
            return value

        def invoke(args, fetcher=fetch):
            observed.clear()
            provider.clear()
            return S.run(args, root=root, agent="alice", binary=binary, env=env,
                         cwd=tmp_path, fetch=fetcher, runner=runner)

        legacy = os.environ.get("SEEDS_ADAPTER_LEGACY_BINARY")
        if legacy:
            with pytest.raises(C.Unavailable):
                S.run(["--quipu", url, *operation], root=root, agent="alice", binary=legacy,
                      env=env, cwd=tmp_path, fetch=fetch, runner=runner)
            assert provider == [] and observed == []
            print(json.dumps({"phase": "old-cli", "provider_calls": len(provider),
                              "http_requests": len(observed)}))
        result = invoke(["--quipu", url, *operation])
        assert result.returncode != 0  # only the fake write refuses
        assert provider == [1]
        assert [auth for _, auth in observed if auth] == ["Bearer " + value]
        print(json.dumps({"phase": "selected", "provider_calls": len(provider),
                          "own_bearer_headers": sum(auth == "Bearer " + value for _, auth in observed),
                          "foreign_bearer_headers": sum(bool(auth) and auth != "Bearer " + value for _, auth in observed)}))
        assert env == original
        with pytest.raises(OSError):
            os.fstat(descriptors[-1])

        echo_selected = True
        echoed = invoke(["--quipu", url, *operation])
        assert echoed.returncode == result.returncode
        assert value.encode() not in echoed.stdout + echoed.stderr
        assert b"[REDACTED]" in echoed.stdout + echoed.stderr
        assert provider == [1]
        echo_selected = False

        value = "rotated-inert-fixture"
        ref["token_sha256"] = hashlib.sha256(value.encode()).hexdigest()
        selection.write_text(json.dumps(config))
        invoke(["--quipu", url, *operation])
        assert [auth for _, auth in observed if auth] == ["Bearer " + value]

        with pytest.raises(C.Unavailable):
            invoke(["--quipu", "http://untrusted.example", *operation])
        assert provider == [] and observed == []

        def unavailable(*args):
            provider.append(1)
            raise RuntimeError("private-body")
        with pytest.raises(C.Unavailable):
            invoke(["--quipu", url, *operation], unavailable)
        assert provider == [1] and observed == []

        project = tmp_path / ".seeds"
        project.mkdir(exist_ok=True)
        project_config = project / "config.toml"
        project_config.write_text(f'[quipu]\nurl="{url}"\n')
        def retarget(*args):
            result = fetch(*args)
            project_config.write_text(f'[quipu]\nurl="{url}/changed"\n')
            return result
        result = invoke(operation, retarget)
        assert result.returncode != 0 and provider == [1] and observed == []
        print(json.dumps({"phase": "retarget-refused", "provider_calls": len(provider),
                          "http_requests": len(observed)}))
        project_config.write_text('[quipu]\nurl="https://untrusted.example"\n')
        with pytest.raises(C.Unavailable):
            invoke(operation)
        assert provider == [] and observed == []

        config["enabled"] = False
        selection.write_text(json.dumps(config))
        invoke(["--quipu", url, *operation])
        assert provider == []
        assert [auth for _, auth in observed if auth] == ["Bearer shared-inert-fixture"]
        print(json.dumps({"phase": "next-deselected", "provider_calls": len(provider),
                          "shared_bearer_headers": sum(auth == "Bearer shared-inert-fixture" for _, auth in observed)}))
        assert env == original
    finally:
        server.shutdown()
        server.server_close()
