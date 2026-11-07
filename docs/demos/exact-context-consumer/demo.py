"""Compare the console contract, then exercise the candidate with fixture reads."""
from contextlib import nullcontext
from pathlib import Path
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from shantytown import cli, work_context, work_context_command as command

BASE = "8181b7f8e8575b703f5efc8b34b83d53e706d0bf"
before = tomllib.loads(subprocess.check_output(
    ["git", "-C", str(ROOT), "show", f"{BASE}:pyproject.toml"], text=True))
after = tomllib.loads((ROOT / "pyproject.toml").read_text())
print("Target: source checkout; synthetic tracker and evidence, no network")
print("Same console-entry probe on base and candidate:")
print("before st-context:", before["project"]["scripts"].get("st-context", "ABSENT"))
print("after  st-context:", after["project"]["scripts"]["st-context"])

command.resolve_root = lambda root: (ROOT, "explicit")
command.command_environment = lambda root, how: nullcontext()
cli._raw_tracker = lambda args: object()

def read(tracker, item, **kwargs):
    return work_context.Context(item, sections=[
        work_context.Section("episodes", rows=[{
            "act": "urn:fixture:evidence-1", "when": "2026-01-01T00:00:00Z",
            "label": "fixture ruling", "gist": "Preserve the exact blocker.",
            "who": "urn:fixture:reviewer"}]),
        work_context.Section("rulings", unknown="TimeoutError: fixture timeout")])

work_context.context = read
print("\nCandidate console main: st-context fixture-123")
assert command.main(["--root", str(ROOT), "fixture-123"]) == 0

def fail(args):
    raise OSError("fixture private detail must not escape")

cli._raw_tracker = fail
print("\nNegative control: unavailable deployment tracker")
assert command.main(["fixture-123"]) == 1
