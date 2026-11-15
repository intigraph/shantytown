"""Compare source-only receipts; no agent is launched or cycled."""
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import types

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from shantytown import resume_launch as after
from shantytown.deferral_notes import provenance
from shantytown.protocols import Agent

BASE = "2016b460badce9ad5630af91c302ddd485f45b42"
before = types.ModuleType("shantytown._before_launch")
before.__package__ = "shantytown"
exec(compile(subprocess.check_output(
    ["git", "show", BASE + ":shantytown/resume_launch.py"], cwd=ROOT),
    "before_launch.py", "exec"), before.__dict__)
now = datetime(2026, 11, 5, 22, tzinfo=timezone.utc)
row = {"notes": provenance("worker", "2026-11-05T21:59:59Z", "")}
options = dict(administrator=True, harness="claude", session="fixture-session",
               cold=True, ordinary=True, live=True, hooks=True, inbox=True, now=now)
print("Source fixture only: no launch, tracker, provider or installed acceptance.")
print("Base:", BASE)
with TemporaryDirectory() as root:
    card = Agent("operator", harness="claude")
    print("Before assigned-Claude receipt:", before.record(root, card, **options))
    try:
        before.validate("operator")
    except ValueError:
        print("Before bare binding: REFUSED")
    print("After assigned-Claude receipt:", after.record(root, card, **options))
    print("After bare binding:", after.evaluate("operator", root, now, row=row)[0])
with TemporaryDirectory() as root:
    print("Context-clear/cycle (cold=False):",
          after.record(root, card, **(options | {"cold": False})))
    assert after.evaluate("operator", root, now, row=row)[0] is False
