"""Compare real digest output with the base and candidate work predicates."""
import hashlib
from pathlib import Path
import subprocess
import types

from shantytown import priority_advisory, ranking_check
from shantytown.protocols import Agent

BASE = "5e5057dde583169d611d02956d80604c3c9cef88"
source = subprocess.check_output(
    ["git", "show", f"{BASE}:shantytown/priority_advisory.py"], text=True)
base = types.ModuleType("shantytown._demo_base_priority")
exec(compile(source, "base/priority_advisory.py", "exec"), base.__dict__)
candidate = priority_advisory.workable
print("Base:", BASE)
print("Candidate predicate SHA256:", hashlib.sha256(
    Path(priority_advisory.__file__).read_bytes()).hexdigest())
held = dict(id="held", title="Actual work", priority=2, status="in_progress",
            assignee="worker", labels=[])
try:
    for label, predicate in [("BEFORE", base.workable), ("AFTER", candidate)]:
        ranking_check.workable = predicate
        for title, expected in [("ASK Stiwi: choose an account", label == "BEFORE"),
                                ("Fix a parser", True)]:
            row = dict(id="candidate", title=title, priority=1, status="open", labels=[])
            text, _ = ranking_check.digest([row], [held, row], [Agent(name="worker")],
                                            {"worker"}, counts="fixture counts")
            advisory = "worker: held P2 <" in text
            print(f"{label}: {title!r} -> advisory={advisory}")
            assert advisory == expected
finally:
    ranking_check.workable = candidate
