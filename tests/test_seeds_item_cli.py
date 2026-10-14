"""Real CLI and HTTP wire regression for compact versus expanded IRI results."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

GRAPH = "https://seeds.local/project/test"
SUBJECT = "https://seeds.local/item/test-one"
SCHEMA = "https://schema.org/"
SEEDS = "https://seeds.local/ontology/"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
XSD = "http://www.w3.org/2001/XMLSchema#"
FACTS = [(RDF + "type", SCHEMA + "Action", "iri"),
         (SCHEMA + "identifier", "test-one", "string"),
         (SCHEMA + "name", "wire positive", "string"),
         (SEEDS + "status", "open", "string"),
         (SEEDS + "priority", "0", "integer"),
         (SCHEMA + "dateModified", "2026-10-12T12:00:00Z", "dateTime")]


def compact(iri):
    for namespace, prefix in [(RDF, "rdf:"), (SCHEMA, "schema:"), (SEEDS, "seeds:")]:
        if iri.startswith(namespace):
            return prefix + iri[len(namespace):]
    return iri


def exercise(tmp_path, *, actual_sd=None, honor_verbose=True):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, payload):
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self.reply({"status": "ok"})

        def do_POST(self):
            assert self.path == "/query", "read-only fixture refuses other operations"
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(data)
            query = data["query"]
            if query.lstrip().startswith("ASK"):
                self.reply({"boolean": False, "result": False})
                return
            bindings = []
            flat = []
            if SUBJECT in query and ("SELECT ?graph ?s ?p" in query or
                                      ("SELECT ?s ?p ?o" in query and "#seeds-ephemeral" not in query)):
                expanded = data.get("verbose") is True and honor_verbose
                for predicate, value, kind in FACTS:
                    term = {"type": "uri" if kind == "iri" else "literal", "value": value}
                    if kind != "iri":
                        term["datatype"] = XSD + kind
                    bindings.append({"s": {"type": "uri", "value": SUBJECT},
                                     "p": {"type": "uri", "value": predicate}, "o": term})
                    flat.append({"graph": GRAPH, "s": SUBJECT,
                                 "p": predicate if expanded else compact(predicate),
                                 "o": (value if "STR(?value) AS ?o" in query else
                                       int(value) if expanded and kind == "integer" else
                                       {"value": value, "datatype": XSD + kind}
                                       if expanded and kind == "dateTime" else
                                       value if expanded or kind != "iri" else compact(value)),
                                 "kind": "iri" if kind == "iri" else XSD + kind})
            self.reply({"rows": flat, "count": len(flat), "truncated": False,
                        "head": {"vars": ["s", "p", "o"]}, "results": {"bindings": bindings}})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = "http://127.0.0.1:" + str(server.server_port)
    home = tmp_path / "home"
    home.mkdir()
    sdk = actual_sd
    if sdk is None:
        sdk = tmp_path / "where-only-sd"
        proof = {"location_source": "--quipu", "quipu_url": url,
                 "prefix": "test", "graph": GRAPH}
        sdk.write_text("#!" + sys.executable + "\nimport json,sys\n"
                       "assert 'where' in sys.argv, 'SDK hydration escaped'\n"
                       "print(json.dumps(" + repr(proof) + "))\n")
        sdk.chmod(0o700)
    env = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
               SHANTY_SD_BIN=str(sdk), SHANTY_SD_QUIPU=url, SHANTY_SD_PREFIX="test",
               SEEDS_GRAPH=GRAPH, SEEDS_PREFIX="test")
    for key in ("SHANTY_SD_STORE", "SEEDS_QUIPU_TOKEN", "QUIPU_AUTH_TOKEN",
                "QUIPU_AUTH_TOKEN_FILE", "SEEDS_QUIPU_URL", "SEEDS_QUIPU_STORE"):
        env.pop(key, None)
    source = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = str(source)
    command = [sys.executable, "-c", "from shantytown.cli import main; raise SystemExit(main())",
               "--root", str(tmp_path / "state"), "--backend", "seeds", "--repo", str(tmp_path),
               "work", "item", "show", "test-one"]
    try:
        result = subprocess.run(command, env=env, cwd=tmp_path, capture_output=True,
                                text=True, timeout=30, check=False)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    return result, requests


def test_real_show_cli_requests_verbose_and_refuses_wrong_wire(tmp_path):
    good, requests = exercise(tmp_path)
    assert good.returncode == 0, good.stderr
    value = json.loads(good.stdout)
    assert (value["id"], value["title"], value["status"], value["priority"]) == (
        "test-one", "wire positive", "open", 0)
    assert len(requests) == 2
    assert requests[-1]["verbose"] is True
    assert "STR(?value) AS ?o" in requests[-1]["query"]
    other = tmp_path / "bad"
    other.mkdir()
    bad, requests = exercise(other, honor_verbose=False)
    assert bad.returncode == 2 and "unexpected item predicate" in bad.stderr
    assert len(requests) == 2


@pytest.mark.real_store
@pytest.mark.skipif(shutil.which("sd") is None, reason="installed SDK integration requires sd")
def test_real_show_cli_with_actual_sdk_and_readonly_http(tmp_path):
    result, requests = exercise(tmp_path, actual_sd=shutil.which("sd"))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["id"] == "test-one"
    assert len(requests) == 2
    assert requests[-1]["verbose"] is True
    assert "STR(?value) AS ?o" in requests[-1]["query"]
