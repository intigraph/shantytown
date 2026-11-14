"""Repeatable offline deferral-reader comparison; no service or board is contacted."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from shantytown import seeds_plate, seeds_read_cache

BASE = "c96be285f052ae5ec709137842240bea0b887ce1"
source = subprocess.check_output(
    ["git", "show", BASE + ":shantytown/seeds_plate.py"], cwd=ROOT, text=True)
before = ModuleType("shantytown._ebu_before")
before.__package__ = "shantytown"
exec(compile(source, "baseline-seeds-plate.py", "exec"), before.__dict__)


def run(label, module, relevant=False):
    graph = "https://example.test/board"
    subject = module.SEEDS + "item/demo-held"
    state = dict(tx=10, queries=0)

    class Response:
        status = 200
        def __init__(self, data): self.data = data
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size): return json.dumps(self.data).encode()

    def watermark(*args):
        state["tx"] += 1  # The board remains busy throughout the read.
        return "offline-demo", state["tx"]

    def send(request, timeout):
        if request.get_method() == "POST":
            state["queries"] += 1
            query = json.loads(request.data)["query"]
            values = dict(id="demo-held", title="held work", status="deferred",
                          priority=1, created_at="2026-10-01T00:00:00Z")
            inverse = {v: k for k, v in module.FIELDS.items()}
            rows = ([dict(subject=subject, graph=graph, predicate=inverse[k], value=v)
                     for k, v in values.items()] if "AS ?predicate" in query else
                    [dict(subject=subject, graph=graph)])
            return Response(dict(rows=rows, count=len(rows), truncated=False))
        params = parse_qs(urlsplit(request.full_url).query)
        since, g = int(params["since"][0]), params["graph"][0]
        record = dict(tx=since + 1, graph=g, entity=module.SEEDS + "item/other",
                      attribute=module.SEEDS + "ontology/status" if relevant else
                      module.SCHEMA + "description", op="assert")
        return Response(dict(since=since, records=[record], next_tx=since + 1,
                             watermark_tx=state["tx"], capture="new_values",
                             source=dict(store_id="offline-demo", log_epoch="demo")))

    original = seeds_read_cache._watermark
    seeds_read_cache._watermark = watermark
    module.urlopen = send
    try:
        with tempfile.TemporaryDirectory() as directory:
            os.environ["XDG_CACHE_HOME"] = directory
            answer = module.deferred_rows(SimpleNamespace(quipu_url="https://example.test",
                                                          graph=graph), timeout=5)
            result = "EXACT: demo-held" if answer.complete else "UNKNOWN: no release"
            print(f"{label}: {result}; query requests={state['queries']}")
            return answer.complete
    finally:
        seeds_read_cache._watermark = original


print("Offline fixture: watermark advances continuously; no network calls.")
print("Base:", BASE)
assert not run("BEFORE, unrelated writes", before)
assert run("AFTER, same unrelated writes", seeds_plate)
assert not run("CONTROL, candidate membership changes", seeds_plate, relevant=True)
