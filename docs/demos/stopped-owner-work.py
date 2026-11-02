"""Offline old-proposal/current-policy comparison; no board, panes or processes."""
import copy
from contextlib import nullcontext
import json
from pathlib import Path
import subprocess
import tempfile
from types import ModuleType
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shantytown.stranded_work import StrandedWork

old = ModuleType("shantytown._old_stranded_demo")
old.__package__ = "shantytown"
root = Path(__file__).resolve().parents[2]
source = subprocess.check_output(["git", "-C", str(root), "show",
    "805a04e:shantytown/stranded_work.py"], text=True)
exec(compile(source, "preserved-805a04e", "exec"), old.__dict__)

def run(cls, priority, status, elapsed):
    with tempfile.TemporaryDirectory() as folder:
        row = dict(id="demo-1", assignee="worker", priority=priority,
                   status=status, title="fixture", labels=[], revision=1)
        notices, releases = [], []
        kwargs = dict(observe=lambda *_: dict(state="down", generation="fixture", resume_at=None),
            recipient=lambda *_: "administrator", notify=lambda *a: notices.append(a),
            read=lambda _: copy.deepcopy(row), release=lambda *a: releases.append(a) or "released",
            checkpoint=lambda *_: dict(worktree="fixture-tree", branch="fixture-branch", checkpoint="retained"),
            fence=lambda _: nullcontext(), release_admitted=True)
        svc = cls(folder)
        svc.tick([row], {}, now=0, **kwargs)
        if elapsed:
            svc.tick([row], {}, now=elapsed, **kwargs)
        return dict(attention=len(notices), releases=len(releases))

for priority,status,elapsed in [(0,"open",0),(1,"open",3601),(1,"in_progress",86401)]:
    print(json.dumps(dict(priority=priority,status=status,measured_seconds=elapsed,
        before=run(old.StrandedWork,priority,status,elapsed),
        after=run(StrandedWork,priority,status,elapsed)),sort_keys=True))
