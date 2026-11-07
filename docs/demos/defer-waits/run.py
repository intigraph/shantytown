"""Compare real deferral code in isolated files fixtures; never contact a board."""
import os
from pathlib import Path
import subprocess
import sys

SOURCE = Path(__file__).resolve().parents[3]
PROBE = r'''
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
from shantytown.dispatch import Dispatcher, DeferRefused
from shantytown.files import FilesRegistry, FilesTracker
from shantytown.tmux import NullPanes
from shantytown.deferral_pacing import OwnerPacing, provenance

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    tracker = FilesTracker(root / "items")
    tracker.update("test-ci", title="fixture", status="open", assignee="worker")
    d = Dispatcher(FilesRegistry(root / "crew"), tracker, NullPanes())
    now = datetime.now(timezone.utc)
    until = (now + timedelta(hours=1)).isoformat(timespec="seconds").replace("+00:00", "Z")
    try:
        d.defer("test-ci", "external", "CI pending", until=until, gate_authority="worker")
        outcome = "ACCEPT"
    except DeferRefused:
        outcome = "REFUSE"
    print("same input: CI pending, one-hour date-only ->", outcome)
    assert outcome == ("ACCEPT" if MODE == "before" else "REFUSE")
    if MODE == "after":
        assert tracker.get("test-ci").status == "open"
        d.defer("test-ci", "external", "scheduled review appointment", until=until,
                window=True, gate_authority="worker")
        print("control: explicit scheduled --window -> ACCEPT")

    end = (now - timedelta(minutes=1)).isoformat()
    item = {"id": "test-owner", "assignee": "worker", "title": "fixture", "labels": [],
            "defer_until": end, "updated_at": (now - timedelta(minutes=15)).isoformat(),
            "notes": provenance("worker", (now - timedelta(minutes=16)).isoformat(), end)}
    routed = []
    for _ in range(3):
        pacing = OwnerPacing(root)
        owner = pacing.route(item, now, lambda _: True, lambda *_: "fixture-delivered")
        routed.append("owner" if owner else "administrator")
        pacing.save()
    print("same expired owner timer, three observations ->", ", ".join(routed))
    assert routed == (["owner", "owner", "administrator"] if MODE == "before"
                       else ["owner", "owner", "owner"])
    print("No resume gate released; fixture only.")
'''

for mode, source in (("before", Path(os.environ["DEFER_DEMO_BASELINE"])), ("after", SOURCE)):
    print(mode.upper(), "isolated library fixture", flush=True)
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("SHANTY_", "ST_", "QUIPU_"))}
    env["PYTHONPATH"] = str(source)
    subprocess.run([sys.executable, "-c", "MODE=" + repr(mode) + "\n" + PROBE],
                   cwd=source, env=env, check=True)
