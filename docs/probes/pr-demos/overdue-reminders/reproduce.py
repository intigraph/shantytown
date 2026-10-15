"""Isolated exact-reader and delivery-sink demonstration; no fleet calls."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from shantytown.answer import Answer
from shantytown.overdue import OverdueAlerter

with tempfile.TemporaryDirectory() as root:
    sent = []
    rows = [dict(id=f"example-{i}", title="Example work", status="open",
                 due_at="2026-10-01T00:00:00Z", assignee="worker", labels=[])
            for i in range(112)]
    reg = SimpleNamespace(get=lambda who: SimpleNamespace(name=who))
    kwargs = dict(read=lambda: Answer.complete_read(rows, how="isolated112itemfixture"),
                  deliver=lambda *args: sent.append(args) or True,
                  now=lambda: datetime(2026, 10, 2, tzinfo=timezone.utc))
    first = OverdueAlerter(root, reg, **kwargs).sweep()
    second = OverdueAlerter(root, reg, **kwargs).sweep()
    print(json.dumps(dict(target="candidate source / isolated read and delivery sink",
                         first_pass_recipients=first, second_pass_recipients=second,
                         actual_messages=len(sent), message=sent[0][2],
                         production_delivery="not invoked"), indent=2))
