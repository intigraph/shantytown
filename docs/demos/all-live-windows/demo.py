"""Actual inbox implementations, synthetic age-aware backend; no live service."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from shantytown.answer import Answer
from shantytown.inbox import MessageGraphInbox

BASE = "39f4bf93a956c57a1b7a7ec7f42be3a46cb4a076"

class Legacy:
    def unread_count(self, who):
        return 0
    def mark_read(self, who, ids):
        return []

class Windows:
    def __init__(self):
        self.read = False
        self.scopes = []
    def list_messages(self, who, *, unread=True, weeks=2, all_windows=False):
        self.scopes.append("all-live" if all_windows else f"recent-{weeks}")
        rows = []
        if all_windows and (not unread or not self.read):
            rows = [{"id": "msg-old-live", "to": who, "text": "old unread mail",
                     "sent_at": "2000-01-03T10:00:00Z", "read_at": "read" if self.read else None}]
        return Answer.complete_read(rows, how="synthetic age-aware backend")
    def read_messages(self, ids, *, weeks=2, all_windows=False):
        assert all_windows
        self.read = True
        return Answer.complete_read([{"id": i, "marked": True} for i in ids], how="synthetic mark")

def run(label, implementation):
    tracker = Windows()
    box = implementation(Legacy(), tracker)
    before = box.unread_count("reader")
    try:
        marked = [m.id for m in box.mark_read("reader", ["msg-old-live"])]
        error = None
    except RuntimeError as exc:
        marked, error = [], str(exc)
    result = {"implementation": label, "unread_before": before, "marked": marked,
              "error": error, "unread_after": box.unread_count("reader"), "scopes": tracker.scopes}
    print(json.dumps(result, sort_keys=True))
    return result

with tempfile.TemporaryDirectory() as tmp:
    source = subprocess.check_output(["git", "show", BASE + ":shantytown/inbox.py"])
    path = Path(tmp) / "baseline.py"
    path.write_bytes(source)
    name = "shantytown._window_demo_baseline"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    baseline = run(BASE, module.MessageGraphInbox)
    candidate = run("d9370924febd29e77c5e41b912e21f969ba88ecd", MessageGraphInbox)
    assert baseline["unread_before"] == 0 and baseline["error"]
    assert candidate["unread_before"] == 1 and candidate["marked"] == ["msg-old-live"]
    assert candidate["unread_after"] == 0 and set(candidate["scopes"]) == {"all-live"}
