"""Compare failed-hook polling on a private clock and ledger; no tracker I/O."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from shantytown import untracked

BASE = "baf725b94621565658c6acf9e8fabd9283068079"

class Registry:
    def get(self, name):
        return SimpleNamespace(name=name, role="worker", reports_to="lead")

class Events:
    def persist(self, **kwargs):
        raise AssertionError("UNKNOWN must not escalate")

def run(module, root):
    clock, calls = [1_000_000.0], []
    def unavailable(who):
        calls.append(who)
        raise RuntimeError("fixture HTTP408")
    for _ in range(20):
        gov = module.Governor(root, Registry(), unavailable, Events(), now=lambda: clock[0])
        verdict = gov.check("fixture")
        assert verdict.action == module.SILENT and "could not read" in verdict.why
        assert not verdict.text
        clock[0] += 1
    assert module.ledger_activity(root, "fixture", now=clock[0])[0] == module.ACTIVITY_UNKNOWN
    return {"hook_invocations": 20, "plate_reads": len(calls), "activity": "UNKNOWN", "warnings": 0}

with tempfile.TemporaryDirectory(prefix="untracked-backoff-") as temp:
    root = Path(temp)
    path = root / "baseline.py"
    path.write_bytes(subprocess.check_output(["git", "show", BASE + ":shantytown/untracked.py"]))
    spec = importlib.util.spec_from_file_location("shantytown._untracked_baseline", path)
    old = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = old
    spec.loader.exec_module(old)
    before, after = run(old, root / "before"), run(untracked, root / "after")
    assert before["plate_reads"] == 20 and after["plate_reads"] == 1
    print(json.dumps({"before": before, "after": after,
        "scope": "private clock, separate Governor instances and private shared ledger; no HTTP or production rate claim"}, indent=2))
