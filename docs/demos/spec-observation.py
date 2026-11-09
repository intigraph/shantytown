"""Repeatable private fixture demonstration, usable on base and candidate source.

Run with PYTHONPATH pointing to the source revision to demonstrate.
This creates no live generation, delivery, hook configuration, or owner ACK.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile

from shantytown.answer import Answer
from shantytown.spec_boundary import consume

try:
    from shantytown import spec_observation as evidence
except ImportError:
    evidence = None


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    rows = [{"id": "work-example", "title": "Example", "status": "open", "priority": 1,
             "assignee": "owner", "spec_version": 2, "spec_previous_version": 1,
             "spec_changed_at": "2026-10-14T23:00:00Z"}]
    kwargs = {"now": datetime(2026, 10, 15, tzinfo=timezone.utc)}
    if evidence:
        kwargs["observation"] = ("codex", {"hook_event_name": "Stop", "session_id": "demo-session",
                                            "hook_run_id": "demo-hook"})
    notice = consume(root, "owner", lambda: Answer.complete_read(rows, how="private fixture"), **kwargs)
    print("Generated notice:", notice)
    print("Duplicate generation:", consume(root, "owner", lambda: Answer.complete_read(rows, how="private fixture"), **kwargs))
    if evidence is None:
        print("Observation reader: unavailable on this revision; the fence does not prove arrival.")
    else:
        record = next((root / "notify/spec-observation").glob("*.json"))
        identity = json.loads(record.read_text())["identity"]
        print("Emission only:", json.dumps(evidence.show(root, identity), sort_keys=True))
        archive = root / "receiver.jsonl"
        header = {"type": "session_meta", "payload": {"id": "demo-session"}}
        turn = {"type": "turn_context", "payload": {"turn_id": "demo-turn"}}
        message = {"type": "response_item", "payload": {"type": "message", "role": "developer",
                   "content": [{"type": "input_text", "text": notice}]}}
        payload = {"session_id": "demo-session", "transcript_path": str(archive)}
        # Same wire bytes, wrong recipient session: must stay UNKNOWN.
        archive.write_text("".join(json.dumps(row) + "\n" for row in
                                    [header | {"payload": {"id": "foreign-session"}}, turn, message]))
        evidence.observe(root, "owner", payload)
        print("Wrong session:", json.dumps(evidence.show(root, identity), sort_keys=True))
        archive.write_text("".join(json.dumps(row) + "\n" for row in [header, turn, message]))
        evidence.observe(root, "owner", payload)
        print("Accepted input fixture:", json.dumps(evidence.show(root, identity), sort_keys=True))
        evidence.observe(root, "owner", payload)
        print("Replay receipt count:", len(evidence.show(root, identity)["receivers"]))
