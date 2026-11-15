"""Exercise the real drain entry point with isolated event and tracker fixtures."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from shantytown import stop_event
from shantytown.answer import Answer
from shantytown.events import FilesEvents


class Tracker:
    def __init__(self):
        self.rosters = []
        self.owner_reads = []

    def prepare_roster(self, owners):
        self.rosters.append(list(owners))

    def plate_rows(self, owner):
        self.owner_reads.append(owner)
        rows = ([dict(id="work-1", title="Current work", assignee=owner,
                      status="in_progress", priority=1)] if owner == "worker" else [])
        return Answer.complete_read(rows, how="isolated fixture")


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    (root / "crew").mkdir()
    for name, role in (("admin", "administrator"), ("lead", "lead"), ("worker", "worker")):
        (root / "crew" / f"{name}.json").write_text(json.dumps(
            dict(role=role, pane=f"p-{name}", reports_to="admin")))
    (root / "shantytown.toml").write_text('[env]\nSHANTY_BACKEND="seeds"\n')
    FilesEvents(root / "events").persist(to="admin", frm="worker", reason="stopped", rose=False)
    tracker = Tracker()
    output = io.StringIO()
    panes = type("Panes", (), {"exists": lambda *args: False})()
    with patch.dict("os.environ", {"SHANTY_AGENT": "admin"}), \
         patch.object(stop_event, "_stop_identity", return_value="admin"), \
         patch.object(stop_event, "Tmux", return_value=panes), \
         patch.object(stop_event, "_liveness", return_value="?"), \
         patch("shantytown.job_launch.local_job", return_value=None), \
         patch("shantytown.sd.br_like_tracker", return_value=tracker), \
         contextlib.redirect_stdout(output):
        result = stop_event.main(["drain", "--root", str(root)])
    reason = json.loads(output.getvalue())["reason"]
    print(json.dumps(dict(exit=result, prepared_rosters=tracker.rosters,
                          owner_reads=tracker.owner_reads,
                          current_work_visible="work-1" in reason,
                          unknown="PLATE UNKNOWN" in reason), sort_keys=True))
