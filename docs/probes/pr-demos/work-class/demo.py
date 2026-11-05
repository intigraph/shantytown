"""Repeat the policy change with private trackers and inert panes only."""
from contextlib import redirect_stderr, redirect_stdout
from hashlib import sha256
from io import StringIO
from pathlib import Path
import os
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
for key in tuple(os.environ):
    if key.startswith(("SHANTY_", "ST_")) or key == "QUIPU_SERVER":
        os.environ.pop(key)

import pytest
from shantytown import cli, work_class
from test_work_class import world, put

BASE = subprocess.check_output(
    ["git", "rev-parse", "c7eb531"], cwd=ROOT, text=True).strip()
old = subprocess.check_output(
    ["git", "show", f"{BASE}:shantytown/work_class.py"], cwd=ROOT, text=True)
new = (ROOT / "shantytown/work_class.py").read_text()
print("Private normal go --dry-run; file tracker + inert panes; no installed CLI")
print("Baseline:", BASE)
print("Candidate module SHA256:", sha256(new.encode()).hexdigest())
cases = [(["work:important-quipu-code"], "coder"),
         (["work:design"], "coder"),
         (["work:important-quipu-code"], "writer"),
         (["work:review"], "coder"),
         (["work:review"], "writer")]
try:
    for phase, source in [("BEFORE", old), ("AFTER", new)]:
        exec(compile(source, "private-policy-snapshot", "exec"), work_class.__dict__)
        for labels, target in cases:
            with TemporaryDirectory(prefix="work-class-demo-") as temporary:
                with pytest.MonkeyPatch.context() as patch:
                    _, tracker, panes = world(Path(temporary), patch)
                    put(tracker, labels)
                    before = tracker._path("job").read_bytes()
                    output = StringIO()
                    with redirect_stdout(output), redirect_stderr(output):
                        result = cli.main(["--root", temporary, "--backend", "files",
                                           "go", "job", target, "--dry-run"])
                    assert tracker._path("job").read_bytes() == before
                    assert not panes.sent
                    expected = target == "coder" if phase == "AFTER" else (
                        target == "writer" if labels != ["work:review"] else target == "coder")
                    assert (result == 0) == expected, output.getvalue()
                    print(f"{phase}: {labels[0]} -> {target}: "
                          f"{'ADMITTED' if result == 0 else 'REFUSED'}; "
                          "tracker unchanged; zero pane sends", flush=True)
                    time.sleep(0.5)
finally:
    exec(compile(new, "candidate-policy-snapshot", "exec"), work_class.__dict__)
