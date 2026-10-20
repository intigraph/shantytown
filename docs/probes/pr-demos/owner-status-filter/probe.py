"""Compare generated selection queries on a disposable native fixture."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

from shantytown import seeds_plate
from shantytown.sd import StoreProof

BASE = "f00120e463995b9582567503107e0db6b2f8960e"
G = "https://example.test/project/demo"
N, S = seeds_plate.SEEDS, seeds_plate.SCHEMA


def selection(module, url):
    seen = []
    module.owner_shape_supported = lambda *a, **kw: True
    module._query = lambda p, q, t: seen.append(q) or {"rows": [], "count": 0, "truncated": False}
    module.owner_rows(StoreProof("fixture", None, url, "demo", G), "worker", decision=True).exact()
    assert len(seen) == 1
    return seen[0]


def request(url, path, payload):
    req = urllib.request.Request(url + path, data=urllib.parse.urlencode(payload).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded", "X-Quipu-Client": "seeds"})
    with urllib.request.urlopen(req, timeout=10) as response:
        body = response.read()
    return json.loads(body) if body else None


def main():
    binary = os.environ.get("QUIPU_SERVER_BIN") or shutil.which("quipu-server")
    if not binary:
        raise SystemExit("set QUIPU_SERVER_BIN or put quipu-server on PATH")
    with tempfile.TemporaryDirectory(prefix="owner-filter-") as temp:
        old_path = Path(temp) / "baseline.py"
        old_path.write_bytes(subprocess.check_output(["git", "show", BASE + ":shantytown/seeds_plate.py"]))
        spec = importlib.util.spec_from_file_location("shantytown._owner_filter_baseline", old_path)
        old = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = old
        spec.loader.exec_module(old)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        process = subprocess.Popen([binary, "--db", temp + "/fixture.db", "--bind", f"127.0.0.1:{port}"],
            cwd=temp, env=dict(os.environ, HOME=temp), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(100):
                try:
                    urllib.request.urlopen(url + "/health", timeout=1).close()
                    break
                except OSError:
                    time.sleep(.1)
            facts, expected = [], []
            for gi, graph in enumerate((G, G + "#seeds-ephemeral", G + "-foreign")):
                triples = []
                for i in range(30):
                    subject = N + f"item/demo-{gi}-{i}"
                    owner = '"other"' if i >= 20 else f'<{N}principal/worker>' if i % 2 else '"worker"'
                    title = '"inbox: message"' if i % 10 == 0 else '"mail: message"' if i % 10 == 1 else '"actual work"'
                    kind = "Thing" if i % 10 == 2 else "Action"
                    status = ("hooked", "in_progress", "open", "blocked", "closed")[i % 5]
                    triples.append(f'<{subject}> a <{S}{kind}> ; <{S}agent> {owner} ; <{S}name> {title} ; <{N}ontology/status> "{status}" .')
                    if gi < 2 and i < 20 and i % 10 not in (0, 1, 2) and status != "closed":
                        expected.append((subject, graph))
                facts.append(f'GRAPH <{graph}> {{ ' + " ".join(triples) + " }")
            request(url, "/update", {"update": "INSERT DATA { " + " ".join(facts) + " }"})
            queries = [selection(old, url), selection(seeds_plate, url)]
            results = []
            for query in queries:
                result = request(url, "/query", {"query": query})
                assert result["head"]["vars"] == ["subject", "graph"], result
                rows = sorted((r["subject"]["value"], r["graph"]["value"]) for r in result["results"]["bindings"])
                assert rows == sorted(expected), (rows, expected)
                results.append({"branches": query.count(" UNION ") + 1, "bytes": len(query.encode()), "rows": len(rows)})
            assert results[0]["branches"] == 16 and results[1]["branches"] == 4
            print(json.dumps({"before": results[0], "after": results[1], "exact_expected_rows_and_headers": True,
                "controls": ["literal owner", "IRI owner", "both graphs", "modern/legacy messages", "wrong type", "other owner", "foreign graph", "closed"],
                "scope": "disposable loopback fixture; shape check bypassed only to isolate candidate selection; normal shape and hydration tests run separately; no production timing claim"}, indent=2))
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
