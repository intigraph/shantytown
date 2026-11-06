"""Compare real condition parsing on base/head, with private forge responses."""
from pathlib import Path
import subprocess
import sys
import types

ROOT = Path(__file__).resolve().parents[3]
BASE = "f9941a35a914ec925a8d2226aade3dcb79b124b8"
sys.path.insert(0, str(ROOT))
from shantytown import deferrals, resume_forge

before = types.ModuleType("before_deferrals")
sys.modules[before.__name__] = before
source = subprocess.check_output(
    ["git", "show", f"{BASE}:shantytown/deferrals.py"], cwd=ROOT, text=True)
exec(compile(source, "before_deferrals.py", "exec"), before.__dict__)
marker = "resume_when: pr-merged:github/owner/repo#7"
print("Library demonstration; private forge fixtures, no network or live tracker writes.")
print("Base:", BASE)
print("Head:", subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip())
print("Same input:", marker)
old, new = before.parse_condition(marker), deferrals.parse_condition(marker)
print("Before: condition testable =", old.testable())
print("After:  condition testable =", new.testable())
assert not old.testable() and new.testable()

for label, merged, repository, expected in (
        ("open PR", False, "owner/repo", False),
        ("matching merged PR", True, "owner/repo", True),
        ("foreign merged PR", True, "other/repo", None)):
    def read(path):
        assert path == "/pulls/7"
        return dict(number=7, merged=merged, base=dict(repo=dict(full_name=repository)),
                    merged_at="2026-11-05T21:00:00Z")
    result, reason = resume_forge.evaluate("pr-merged", "github/owner/repo#7", read=read)
    print(f"{label}: ready={result}; {reason}")
    assert result is expected
print("PASS: only matching positive merge evidence satisfies the condition.")
