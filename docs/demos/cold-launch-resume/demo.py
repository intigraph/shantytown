"""Library-only cold-launch observation; no process or tracker is started."""
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import sys
import types
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from shantytown import deferrals, resume_launch
from shantytown.protocols import Agent
BASE = "a2afbdf4660908757245f349b826d5707c6e22f9"
before = types.ModuleType("before_deferrals")
sys.modules[before.__name__] = before
exec(compile(subprocess.check_output(["git", "show", BASE + ":shantytown/deferrals.py"], cwd=ROOT), "before_deferrals.py", "exec"), before.__dict__)
marker = "resume_when: cold-launch:operator@2026-11-05T21:00:00Z"
print("Library fixture only: no network, tracker mutation, crew launch or cycle.")
print("Same marker:", marker)
print("Before: testable =", before.parse_condition(marker).testable())
print("After: testable =", deferrals.parse_condition(marker).testable())
assert not before.parse_condition(marker).testable()
assert deferrals.parse_condition(marker).testable()
now = datetime(2026, 11, 5, 22, tzinfo=timezone.utc)
arg = deferrals.parse_condition(marker).arg
with TemporaryDirectory() as root:
    print("Before receipt:", resume_launch.evaluate(arg, root, now)[0])
    options = dict(administrator=True, harness="codex", session="synthetic-session", cold=True, ordinary=True, live=True, hooks=True, inbox=True, now=now)
    assert not resume_launch.record(root, Agent("operator", harness="codex"), **(options | {"ordinary": False}))
    print("Hold-override fixture:", resume_launch.evaluate(arg, root, now)[0])
    assert resume_launch.record(root, Agent("operator", harness="codex"), **options)
    assert resume_launch.evaluate(arg, root, now)[0] is True
    print("Verified ordinary fixture receipt:", resume_launch.evaluate(arg, root, now)[0])
print("PASS: receipt observation only; installed and natural-launch acceptance remain separate.")
