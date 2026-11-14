"""Actual stop-hook before/after with an isolated exact-head CI reader fixture."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from shantytown import quiet_waits, deferrals, stop_event
from shantytown.protocols import Agent
from test_haul import _Reg, _Panes
from test_resume_forge_events import fake_ci

BASE = "c96be285"
source = subprocess.check_output(["git", "show", BASE + ":shantytown/stop_event.py"], cwd=ROOT, text=True)
before = types.ModuleType("shantytown.stop_event_before")
before.__package__ = "shantytown"
before.__file__ = str(ROOT / "shantytown/stop_event.py")
exec(compile(source, before.__file__, "exec"), before.__dict__)
item = {"id": "demo-work", "title": "CI wait", "assignee": "demo", "status": "in_progress",
        "notes": "resume_when: ci-terminal:github/example/project@" + "a" * 40}
card = Agent(name="demo", role="worker", pane="demo", harness="codex")
for label, module, terminal in [("base/pending", before, False), ("candidate/pending", stop_event, False),
                                ("candidate/terminal-failure", stop_event, True)]:
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(module, "_bd_json", lambda args, *a, **kw: [item] if args[0] == "list" else [])
        reader = fake_ci(run_status="completed" if terminal else "queued", conclusion="failure" if terminal else None)
        patch.setattr(quiet_waits, "evaluate", lambda rows, now, root:
                      deferrals.evaluate(rows, now, root=root, forge_reader=reader))
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            code = module._haul(_Reg([card]), _Panes({"demo": "❯ "}), "demo", None)
        sent = bool(output.getvalue().strip())
        print(json.dumps({"case": label, "resume_sent": sent, "status": item["status"],
                          "has_defer_date": "defer_until" in item, "exit": code}))
        assert sent == (module is before or terminal)
