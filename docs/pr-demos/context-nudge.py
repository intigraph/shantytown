"""Replay the same isolated administrator usage at a selected source checkout.

Usage: python3 context-nudge.py --source /path/to/checkout
No live crew, model, provider, or tracker calls. Only temporary fixture state.
"""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile

ap = argparse.ArgumentParser()
ap.add_argument("--source", required=True)
a = ap.parse_args()
sys.path.insert(0, str(Path(a.source).resolve()))
for key in ("SHANTY_CONTEXT_JEV_COMMAND", "SHANTY_CREATE_JEV_COMMAND"):
    os.environ.pop(key, None)
from shantytown import context_hint as ch
from shantytown.protocols import Agent

clock = [1000]
ch.time.time = lambda: clock[0]
with tempfile.TemporaryDirectory(prefix="context-nudge-") as tmp:
    root = Path(tmp)
    (root / "shantytown.toml").write_text(
        "[session_budget]\ncontext_window=1000000\ncontext_threshold_pct=70\ncontext_hard_pct=75\n")
    (root / "crew").mkdir()
    (root / "crew/demo.json").write_text('{"role":"administrator"}')
    transcript = root / "session.jsonl"
    payload = dict(session_id="synthetic-admin", transcript_path=str(transcript), hook_event_name="PostToolUse")
    card = Agent(name="demo", role="administrator")
    def observe(label, tokens, tool=False):
        transcript.write_text(json.dumps({"message": {"usage": {
            "input_tokens": 2, "cache_read_input_tokens": tokens-2,
            "cache_creation_input_tokens": 0}}}) + "\n")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            if tool:
                fn = getattr(ch, "tool_feedback", None)
                emitted = fn(root, card.name, payload) if fn else False
            else:
                emitted = ch.emit(root, card, payload)
        result = json.loads(out.getvalue()) if out.getvalue() else {}
        message = result.get("reason") or result.get("hookSpecificOutput", {}).get("additionalContext", "")
        print(json.dumps(dict(probe=label, emitted=emitted, feedback=message.split(";")[0])))
        return emitted
    observe("55% PostToolUse preparation", 550000, tool=True)
    observe("55% Stop preparation", 550000)
    observe("70% first Stop handoff", 700000)
    for seconds in (30, 60, 90):
        clock[0] = 1000 + seconds
        observe(f"70% busy observation +{seconds}s", 700000)
    clock[0] = 1120
    observe("70% Stop handoff +120s", 700000)
    print(json.dumps(dict(auto_cycle_scheduled=(root / "notify/cycle-requests.json").exists(),
                         sticky_work_ceiling=(root / "session_budget").exists())))
