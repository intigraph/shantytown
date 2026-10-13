"""Same simulated HTTP 408, empty-composer probe on base and current source.

Run from the repo root: python3 docs/demos/cycle-resume/demo.py BASE_SHA
"""
import ast
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from argparse import Namespace
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from shantytown import cli, session_anchor, context_hint
from shantytown.tmux import NullPanes
from shantytown.protocols import Agent

base = sys.argv[1]
old_source = subprocess.check_output(["git", "show", f"{base}:shantytown/cli.py"], text=True)
node = next(n for n in ast.parse(old_source).body
            if isinstance(n, ast.FunctionDef) and n.name == "_redispatch_after_cycle")
old = dict(cli.__dict__)
exec(compile(ast.Module(body=[node], type_ignores=[]), "base-cycle", "exec"), old)

with tempfile.TemporaryDirectory() as tmp:
    panes = NullPanes(screen="❯ ")
    args = Namespace(root=Path(tmp))
    def failed_plate(*args, **kw):
        raise RuntimeError("simulated HTTP 408")
    substitutes = dict(_tracker=lambda a: object(), _tracker_plate=failed_plate,
                       _panes=lambda a: panes,
                       _registry=lambda a: SimpleNamespace(get=lambda who: Agent(who, pane="private-pane")))
    old.update(substitutes)
    cli.__dict__.update(substitutes)
    for label, fn in (("BASE", old["_redispatch_after_cycle"]),
                      ("HEAD", cli._redispatch_after_cycle)):
        start = len(panes.sent)
        print(f"{label}: same simulated HTTP 408 after a clear")
        fn(args, "worker", "x-checkpoint")
        print(f"submitted prompts: {len(panes.sent) - start}")
    assert len(panes.sent) == 1
    print("HEAD prompt:", panes.sent[0][1])
    session_anchor._run_anchor = lambda *a: (0, "You are worker — worker.\nON YOUR PLATE\n  x-1 task\n")
    import os
    os.environ.update(SHANTY_ROOT=tmp, SHANTY_AGENT="worker")
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        session_anchor.main([])
    hook = json.loads(captured.getvalue())
    print("HEAD visible plate:", "ON YOUR PLATE" in hook["systemMessage"])
    print("HEAD model plate:", "ON YOUR PLATE" in hook["hookSpecificOutput"]["additionalContext"])
    Path(tmp, "shantytown.toml").write_text('[session_budget]\ncontext_window=1000\ncontext_threshold_pct=70\n')
    transcript = Path(tmp, "fresh.jsonl")
    transcript.write_text(json.dumps({"message":{"usage":{"input_tokens":710}}}) + "\n")
    payload = {"session_id":"fresh", "transcript_path":str(transcript)}
    with contextlib.redirect_stdout(io.StringIO()):
        first = context_hint.emit(tmp, Agent("worker"), payload)
        repeated = context_hint.emit(tmp, Agent("worker"), payload)
    print("HEAD threshold hint: first=", first, "repeat=", repeated)
