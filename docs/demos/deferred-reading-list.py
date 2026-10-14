"""Run against a chosen checkout; disposable snapshot, no board or pane access."""
import json
from pathlib import Path
import sys
import tempfile
from datetime import datetime, timezone, timedelta

sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parents[2]))
from shantytown import deferrals
from shantytown.notify import DeferralAlerter

now = datetime(2026, 10, 13, tzinfo=timezone.utc)
old = {"id": "reading-fixture", "title": "future gate fixture", "priority": 3,
       "status": "deferred", "assignee": "fixture", "notes": "",
       "updated_at": (now - timedelta(days=40)).isoformat(),
       "defer_until": (now + timedelta(days=10)).isoformat()}
control = {**old, "defer_until": (now - timedelta(days=1)).isoformat()}
def forbidden(*args):
    raise AssertionError("reading-list must not wake a pane")
with tempfile.TemporaryDirectory() as directory:
    alerter = DeferralAlerter(directory, None, None, read=lambda: [old],
                             now=now, push=forbidden)
    print("Future gate mechanical findings:", len(alerter.sweep()))
    report = Path(directory) / "notify/deferred-reading-list.json"
    if report.exists():
        data = json.loads(report.read_text())
        print("Reading report:", data["confidence"],
              "old items:", len(data["untouched_30d"]),
              "unknown ages:", len(data["age_unknown"]))
    else:
        print("Reading report: ABSENT; age coverage UNKNOWN")
    print("Lapsed positive control:", len(deferrals.evaluate([control], now)))
