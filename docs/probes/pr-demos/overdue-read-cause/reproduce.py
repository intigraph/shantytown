"""Private library fixture: no network requests or real delivery."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
from urllib.error import HTTPError

BASE = "6f573562c55ff62841cb5878d8822a37825a9069"
parser = argparse.ArgumentParser()
parser.add_argument("--child")
args = parser.parse_args()
if args.child:
    source = Path(args.child).resolve()
    sys.path.insert(0, str(source))
    from shantytown import seeds_plate
    from shantytown.overdue import OverdueAlerter
    assert Path(seeds_plate.__file__).resolve().is_relative_to(source)
    proof = SimpleNamespace(graph="https://example.test/board")
    cases = []
    for failure in (True, False):
        logs, calls, sends = [], [], []
        def query(*_args, **_kwargs):
            calls.append(1)
            if failure:
                raise HTTPError("https://invalid.example/private-value", 408, "private-value", {}, None)
            return {"rows": []}
        seeds_plate._query = query
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            if failure:
                (root / "notify").mkdir()
                ledger = root / "notify/overdue.json"
                ledger.write_text(json.dumps({"entries": {}, "pending": {"admin": {"attempted": True}}}))
                before = ledger.read_bytes()
            result = OverdueAlerter(root, None, read=lambda: seeds_plate.due_rows(proof),
                deliver=lambda *values: sends.append(values), log=logs.append).sweep()
            preserved = not failure or before == ledger.read_bytes()
        assert result == [] and len(calls) == 1 and not sends and preserved
        assert all("private-value" not in line and "https://" not in line for line in logs)
        cases.append({"input": "HTTP 408" if failure else "complete empty rows",
            "log": logs, "reads": len(calls), "production_http": 0,
            "deliveries": len(sends), "pending_preserved": preserved})
    print(json.dumps({"cases": cases}, indent=2))
else:
    root = Path(__file__).resolve().parents[4]
    with tempfile.TemporaryDirectory() as directory:
        archive = Path(directory) / "base.tar"
        with archive.open("wb") as output:
            subprocess.run(["git", "archive", BASE, "shantytown"], cwd=root, stdout=output, check=True)
        before = Path(directory) / "base"
        before.mkdir()
        with tarfile.open(archive) as data:
            data.extractall(before, filter="data")
        for label, source in (("BASE " + BASE, before), ("CANDIDATE " + subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(), root)):
            print(label, flush=True)
            subprocess.run([sys.executable, str(Path(__file__).resolve()), "--child", str(source)], check=True)
