"""Run from an isolated base or candidate source tree; no live dispatch."""
import hashlib
import json
import runpy
import sys
import tempfile
from pathlib import Path

source, label = Path(sys.argv[1]).resolve(), sys.argv[2]
sys.path[:0] = [str(source), str(source / "tests")]
sweep = runpy.run_path(str(source / "tests/test_ceiling_transfer.py"))["_sweep"]
print("source:", label, "target: isolated fixture, injected dispatcher")
for case, options in [("ready", {}), ("unproven", {"dispatch_raises": RuntimeError("fixture refusal")})]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        outcomes, sent, comments, _ = sweep(root, **options)
        path = root / "ceiling-transfer-advisory.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        result = dict(case=case, sends=len(sent), moved=sum(o.moved for o in outcomes),
                      comments=len(comments), legacy_success_ledger=(root / "ceiling-transfers.jsonl").exists(),
                      advisory_phases=[r["phase"] for r in rows],
                      adjudication=sorted({r["adjudication"] for r in rows}))
        print(json.dumps(result, sort_keys=True))
        assert len(sent) == 1
        assert bool(result["moved"]) == (case == "ready")
        if rows:
            assert result["advisory_phases"] == ["start", "plan", "outcomes"]
            assert result["adjudication"] == ["ungraded"]
            assert rows[-1]["inputs"]["outcomes"][0]["disposition"] == (
                "confirmed" if case == "ready" else "unproven")
for name in ("cli.py", "ceiling_transfer.py", "ceiling_advisory.py"):
    path = source / "shantytown" / name
    if path.exists():
        print("sha256", name, hashlib.sha256(path.read_bytes()).hexdigest())
print("Operational false-positive rate: UNKNOWN; no natural exposure or independent grading")
