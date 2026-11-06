"""Owner pacing changes the reminder recipient, never the resume gate."""
import json
from datetime import timedelta
from pathlib import Path

from .ask_visibility import is_ask
from .deferrals import parse_stamp
from .deferral_notes import PROVENANCE_PREFIX as PREFIX, provenance, parse_provenance
from .files import write_json_atomic

OWNER_ONLY_CEILING = timedelta(hours=72)

def owner_window(row, now, *, event_ready=False):
    """Unknown/legacy provenance cannot earn the owner-only route."""
    if is_ask(row):
        return False
    lines = [line for line in str(row.get("notes") or "").splitlines()
             if line.lstrip().startswith(PREFIX.rstrip(": "))]
    # Count malformed/indented candidates too: none may hide behind a valid last line.
    if len(lines) != 1:
        return False
    try:
        value = parse_provenance(lines[0])
        if value is None:
            return False
        start = parse_stamp(value["set_at"])
        end = parse_stamp(value["until"])
        current = parse_stamp(row.get("defer_until"))
        return bool(row.get("assignee") and value["actor"] == row["assignee"]
                    and start and end and end == current
                    and (end <= now or event_ready)
                    and start <= now and start < end)
    except (ValueError, TypeError, KeyError):
        return False


class OwnerPacing:
    """A live owner gets 72 hours without progress; sweep count is not evidence."""
    def __init__(self, root):
        self.path = Path(root) / "notify" / "deferral-owner-pacing.json"
        try:
            self.previous = json.loads(self.path.read_text())
            if not isinstance(self.previous, dict):
                self.previous = {}
        except (OSError, ValueError):
            self.previous = {}
        self.current = {}

    def route(self, row, now, live, deliver, *, event_ready=False):
        if not owner_window(row, now, event_ready=event_ready) or not live(row["assignee"]):
            return False
        key = [row.get("updated_at"), row.get("notes"), row.get("defer_until"), event_ready]
        # Without a touch identity we cannot detect lack of item progress.
        touched = parse_stamp(row.get("updated_at"))
        if touched is None or touched > now:
            return False
        deadline = parse_stamp(row.get("defer_until"))
        # Neither an old item with a fresh deadline nor a freshly updated item
        # with an old deadline has been neglected for the full ceiling.
        if now - max(deadline, touched) >= OWNER_ONLY_CEILING:
            return False  # existing administrator ledger deduplicates this state
        old = self.previous.get(row["id"], {})
        if not isinstance(old, dict) or old.get("key") != key:
            old = {}
        state = {"key": key, "nudged": old.get("nudged") is True}
        self.current[row["id"]] = state
        if not state["nudged"]:
            try:
                sent = deliver(row["assignee"],
                               f"OWNER-PACING: {row['id']} owner-set defer "
                               + ("event is ready" if event_ready else "backstop lapsed")
                               + "; check the current gate and update the item. No gate released.")
            except Exception:
                sent = None
            if not sent:
                return False
            state["nudged"] = True
        return True

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(self.path, self.current)
