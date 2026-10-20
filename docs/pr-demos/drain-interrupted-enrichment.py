"""Actual base/candidate drain code with an isolated in-memory event store."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shantytown import stop_event
from shantytown.events import NullEvents

base = sys.argv[1]
source = subprocess.check_output(
    ["git", "show", base + ":shantytown/stop_event.py"], text=True)
spec = importlib.util.spec_from_loader("shantytown._demo_base_drain", loader=None)
old = importlib.util.module_from_spec(spec)
exec(compile(source, "<base drain>", "exec"), old.__dict__)


def deadline(_name):
    raise KeyboardInterrupt("simulated hook deadline during tracker read")


for label, module, expected in [("BASE", old, 0), ("CANDIDATE", stop_event, 1)]:
    events = NullEvents()
    events.persist(to="lead", frm="worker", reason=None, rose=False)
    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output):
            module._drain(events, "lead", plate=deadline)
    except KeyboardInterrupt:
        pass
    pending = len(events.pending("lead"))
    print(label, "interrupted enrichment:", json.dumps(
        {"model_response_emitted": bool(output.getvalue()), "pending": pending}))
    assert not output.getvalue() and pending == expected
    with contextlib.redirect_stdout(output):
        module._drain(events, "lead")
    print(label, "next drain:", json.dumps(
        {"model_response_emitted": bool(output.getvalue()),
         "pending": len(events.pending("lead"))}))
    if label == "CANDIDATE":
        assert json.loads(output.getvalue())["decision"] == "block"
        silent = io.StringIO()
        with contextlib.redirect_stdout(silent):
            module._drain(events, "lead")
        assert not silent.getvalue()
        print("CONTROL: third drain is silent; delivered reports do not repeat")
print("LIMIT: simulated deadline and memory store; no installed runtime claim")
