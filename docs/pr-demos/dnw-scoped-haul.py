"""Private-free library demo: mocked backend, actual base/head stop-hook code."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shantytown import feed_check, stop_event
from shantytown.answer import Answer, PartialAnswer

base = sys.argv[1]
source = subprocess.check_output(
    ["git", "show", base + ":shantytown/stop_event.py"], text=True)
spec = importlib.util.spec_from_loader("shantytown._demo_old_stop", loader=None)
old = importlib.util.module_from_spec(spec)
exec(compile(source, "<base stop hook>", "exec"), old.__dict__)
rows = [dict(id="foreign", title="work", assignee="other"),
        dict(id="own-parked", title="work", assignee="crew/worker",
             defer_until="2099-01-01T00:00:00Z")]
root = Path("fixture-root")
calls = []
def global_read(args, *a, **kw):
    calls.append(args)
    return rows
with patch.object(old, "_bd_json", global_read):
    before = old._assigned_to("worker", old._bd_json(
        ["list", "--status", "in_progress", "--limit", "0"], None))
print("BASE", json.dumps(dict(anchors=[r["id"] for r in before], global_reads=len(calls))))
tracker = SimpleNamespace(haul_active_rows=lambda owner: Answer.complete_read(
    [rows[1]], how="mocked owner scope"))
with patch.object(feed_check, "_br_tracker", return_value=tracker), patch.object(
        stop_event, "_bd_json", side_effect=AssertionError("global hydration")):
    after = stop_event._haul_active("worker", None, root, None)
    assert before == after
    print("HEAD", json.dumps(dict(anchors=[r["id"] for r in after], global_reads=0,
                                  future_parked_retained=True)))
    tracker.haul_active_rows = lambda owner: Answer.capped(
        [], how="mocked owner scope", caveat="truncated")
    try:
        stop_event._haul_active("worker", None, root, None)
    except PartialAnswer:
        print("NEGATIVE partial owner read: REFUSED; no global fallback")
    else:
        raise AssertionError("partial read treated as empty")
print("LIMIT: mocked backend library demo; no native cost or fleet reduction claim")
