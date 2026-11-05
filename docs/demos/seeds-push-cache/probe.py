"""Synthetic before/after probe; run from the repository root.

python docs/demos/seeds-push-cache/probe.py /path/to/base-seeds_read_cache.py
The base module must come from the revision named in the caption.
"""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from shantytown import seeds_read_cache

spec = importlib.util.spec_from_file_location("shantytown.baseline_cache", sys.argv[1])
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)


class Response:
    status = 200

    def __init__(self, state):
        self.body = json.dumps({"store_id": "fixture", "watermark_tx": state["tx"]}).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def read(self, _limit):
        return self.body


for label, cache in (("base", baseline), ("candidate", seeds_read_cache)):
    state = dict(tx=1, queries=0, watermarks=0)
    clock = [1000.]
    cache.time = SimpleNamespace(time=lambda: clock[0], monotonic=time.monotonic, sleep=time.sleep)

    def opener(request, **_):
        assert request.full_url == "https://graph.example/watermark"
        state["watermarks"] += 1
        return Response(state)

    def fetch():
        state["queries"] += 1
        return {"tx": state["tx"]}

    with tempfile.TemporaryDirectory() as directory:
        os.environ["XDG_CACHE_HOME"] = directory
        os.environ.pop("ST_SEEDS_READ_CACHE", None)
        for _ in range(12):
            assert cache.read("https://graph.example", "SELECT fixture", 5,
                              opener=opener, fetch=fetch, validate=lambda r: r) == {"tx": 1}
        print(f"{label}: 12 identical reads -> queries={state['queries']}, watermarks={state['watermarks']}")
        state["tx"] = 2
        clock[0] += 1
        result = cache.read("https://graph.example", "SELECT fixture", 5,
                            opener=opener, fetch=fetch, validate=lambda r: r)
        assert result == {"tx": 2}
        print(f"{label}: after window expiry + write -> tx={result['tx']} (positive invalidation control)")
