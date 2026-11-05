"""Record actual base/head queries against one disposable synthetic store."""
import collections
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[3]
BASE = "878f24ea0743f8e0a49e2f9f4fb98aa150a59aa0"
sys.path.insert(0, str(ROOT))
from shantytown import seeds_item  # noqa: E402


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    binary = os.environ.get("QUIPU_NATIVE_TEST_BIN")
    if not binary:
        raise SystemExit("Set QUIPU_NATIVE_TEST_BIN to a reviewed Quipu executable.")
    controls = load("native_item_controls", ROOT / "tests/test_seeds_item_native.py")
    source = subprocess.run(
        ["git", "show", BASE + ":shantytown/seeds_item.py"], cwd=ROOT,
        check=True, capture_output=True, text=True,
    ).stdout
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                          check=True, capture_output=True, text=True).stdout.strip()
    print("Target: synthetic local store; no service or deployment access.")
    print("Base:", BASE)
    print("Candidate:", head)
    with tempfile.TemporaryDirectory(prefix="item-query-demo-") as directory:
        root = Path(directory)
        baseline_file = root / "baseline.py"
        baseline_file.write_text(source)
        baseline = load("shantytown._demo_baseline_item", baseline_file)
        run = controls.native_fixture(root / "fixture", binary, unrelated=250)
        print(run("--version"), end="")
        print("Input: item/plain, no blockers, 250 unrelated items per graph.")
        graphs = (controls.GRAPH, controls.GRAPH + "#seeds-ephemeral")
        subject = seeds_item.SEEDS + "item/plain"
        seen = []
        for label, module in (("base", baseline), ("candidate", seeds_item)):
            query = module._fields_query(graphs, subject)
            print(f"\n$ qp read <{label} query> --db <synthetic fixture>")
            print("Query SHA256:", hashlib.sha256(query.encode()).hexdigest())
            started = time.monotonic()
            output = run("read", query)
            elapsed = time.monotonic() - started
            rows = controls.native_rows(output)
            for row in rows:
                predicate = row["p"].rsplit("/", 1)[-1].rsplit("#", 1)[-1]
                kind = row["kind"].rsplit("#", 1)[-1]
                print(f"  {predicate} = {json.dumps(row['o'])} [{kind}]")
            assert len(rows) == 5, "populated item control failed"
            seen.append(collections.Counter(json.dumps(row, sort_keys=True) for row in rows))
            print(f"Elapsed: {elapsed * 1000:.3f} ms")
        assert seen[0] == seen[1], "row multiplicity or metadata changed"
        absent = seeds_item._fields_query(graphs, seeds_item.SEEDS + "item/absent")
        assert controls.native_rows(run("read", absent)) == []
        print("\nPASS: identical row bags; populated control=5, absent control=0.")
        print("Small fixture timings are illustrative, not a production latency guarantee.")


if __name__ == "__main__":
    main()
