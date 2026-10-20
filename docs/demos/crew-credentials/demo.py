"""Synthetic source demo. Never reads real credentials or contacts a server."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(root))
from shantytown import crew_credentials as C
from shantytown import provision as P

base = "f057406faf225701fdeb61a3de920a8d733a7757"
source = subprocess.check_output(["git", "show", base + ":shantytown/provision.py"], cwd=root, text=True)
node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "_codex_servers")
namespace = {}
exec(compile(ast.Module(body=[node], type_ignores=[]), "<base-helper>", "exec"), namespace)
sample = {"probe": {"type": "http", "url": "http://example.invalid/mcp",
                    "headersHelper": "read-volatile-header"}}
print("Same helper input, base then candidate:")
for label, translate in [("base", namespace["_codex_servers"]), ("candidate", P._codex_servers)]:
    got = translate(sample)["probe"]
    print(json.dumps({"revision": label, "native_helper": "http_headers_helper" in got}))
with tempfile.TemporaryDirectory() as directory:
    private = Path(directory)
    provision = private / "provision"
    provision.mkdir()
    runtime = private / "runtime"
    runtime.mkdir(mode=0o700)
    token = "synthetic-named"
    principal = "urn:crew:alice"
    ref = dict(audience="homelab-mcp", project="fixture", path="/mcp-crew/alice",
               key="CREW_" + hashlib.sha256(principal.encode()).hexdigest()[:24].upper() + "_HOMELAB_MCP",
               secret_id="fixture-id", secret_version=1,
               token_sha256=hashlib.sha256(token.encode()).hexdigest(), shared_key="DEMO_SHARED")
    config = dict(version=1, enabled=True, server="http://example.invalid",
                  agents={"alice": dict(principal=principal, servers={"probe": ref})})
    path = provision / "crew-credentials.json"
    path.write_text(json.dumps(config))
    path.chmod(0o600)
    (provision / "secrets.env").write_text("DEMO_SHARED=synthetic-shared\n")
    servers = {"probe": {"type": "http", "url": "http://example.invalid/mcp",
                         "headers": {"Authorization": "Bearer synthetic-shared"}}}
    with patch.object(C, "_directory", return_value=runtime):
        result = C.project(servers, private, "alice", "codex", fetch=lambda *args: token)
        print(json.dumps({"candidate": "materialized", "mode": oct((runtime / "probe").stat().st_mode & 0o777),
                          "persistent_named_bearer": token in json.dumps(result),
                          "named_header_selected": C.headers(private, "alice", "probe")["Authorization"] == "Bearer " + token}))
        (runtime / "probe").unlink()
        print(json.dumps({"candidate": "file deleted",
                          "next_helper_shared_fallback": C.headers(private, "alice", "probe")["Authorization"] == "Bearer synthetic-shared"}))
print("Scope: synthetic fetch and runtime directory; no installed-client or revocation claim.")
