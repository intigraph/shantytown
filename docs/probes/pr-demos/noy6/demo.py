"""Read-only normal dispatch demonstration with private trackers/inert panes."""
from contextlib import redirect_stderr, redirect_stdout
from hashlib import sha256
from io import StringIO
from pathlib import Path
import os
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
for key in tuple(os.environ):
    if key.startswith(("SHANTY_", "ST_")) or key == "QUIPU_SERVER":
        os.environ.pop(key)

import pytest
from shantytown import cli, work_class
from test_work_class import put, world

BASE = "2300f4d594b4c711f59433a8de2246a1cd6b1cf2"
old = subprocess.check_output(["git", "show", f"{BASE}:shantytown/work_class.py"], cwd=ROOT, text=True)
new = (ROOT / "shantytown/work_class.py").read_text()
print("Private normal go --dry-run; no installed CLI or live dispatch")
print("Base:", BASE)
print("Candidate module SHA256:", sha256(new.encode()).hexdigest())
cases = [(["work:design", "work:claude-authorized"], "writer", True),
         (["work:important-quipu-code", "work:claude-authorized"], "writer", True),
         (["work:design"], "writer", False),
         (["work:docs", "work:claude-authorized"], "writer", False),
         (["work:design", "work:claude-authorized", "work:review"], "writer", False),
         ([], "coder", True)]
try:
    for phase, source in [("BEFORE", old), ("AFTER", new)]:
        exec(compile(source, "private-policy-snapshot", "exec"), work_class.__dict__)
        for labels, target, allowed in cases:
            with TemporaryDirectory(prefix="task-authorization-demo-") as directory:
                with pytest.MonkeyPatch.context() as patch:
                    _, tracker, panes = world(Path(directory), patch)
                    put(tracker, labels)
                    tracker.update("job", priority=0)
                    before = tracker._path("job").read_bytes()
                    output = StringIO()
                    with redirect_stdout(output), redirect_stderr(output):
                        code = cli.main(["--root", directory, "--backend", "files", "go", "job", target, "--dry-run"])
                    assert (code == 0) is (allowed if phase == "AFTER" else target == "coder"), output.getvalue()
                    assert tracker._path("job").read_bytes() == before
                    assert not panes.sent
                    print(f"{phase}: {labels} -> {target}: {'ADMITTED' if code == 0 else 'REFUSED'}; tracker unchanged; zero pane sends", flush=True)
finally:
    exec(compile(new, "candidate-policy-snapshot", "exec"), work_class.__dict__)
