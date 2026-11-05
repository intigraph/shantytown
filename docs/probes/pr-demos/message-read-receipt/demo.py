"""A deliberately incomplete transport receipt; never opens a real store."""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
sys.path.insert(0, str(Path(os.environ["SOURCE_DIR"]).resolve()))
from shantytown.sd import SdTracker
tracker = object.__new__(SdTracker)
tracker._bd = lambda *args: SimpleNamespace(returncode=0, stdout=json.dumps([
    {"id":"msg-one", "marked":True}]), stderr="")
print("request: mark msg-one and msg-two read")
print("transport response: receipt for msg-one only")
try:
    answer = tracker.read_messages(["msg-one", "msg-two"])
    value = answer.exact() if hasattr(answer, "exact") else answer
    print(f"accepted incomplete response: {len(value)} receipt for 2 requested IDs")
except RuntimeError as error:
    print(f"refused: {error}")
