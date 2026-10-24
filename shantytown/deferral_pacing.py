"""Owner pacing changes the reminder recipient, never the resume gate."""
import json
from pathlib import Path

from .ask_visibility import is_ask
from .deferrals import parse_stamp
from .deferral_notes import PROVENANCE_PREFIX as PREFIX, provenance, parse_provenance
from .files import write_json_atomic

LIMIT = 3


def owner_window(row, now):
    """Unknown/legacy provenance cannot earn the owner-only route."""
    if is_ask(row):
        return False
    lines = [line for line in str(row.get("notes") or "").splitlines()
             if line.startswith(PREFIX)]
    if not lines:
        return False
    try:
        value = parse_provenance(lines[-1])
        if value is None:
            return False
        start = parse_stamp(value["set_at"])
        end = parse_stamp(value["until"])
        current = parse_stamp(row.get("defer_until"))
        return bool(row.get("assignee") and value["actor"] == row["assignee"]
                    and start and end and end == current and end <= now
                    and 0 < (end - start).total_seconds() <= 3600)
    except (ValueError, TypeError, KeyError):
        return False


class OwnerPacing:
    """Three unchanged observations escalate, even after a delivered nudge."""
    def __init__(self, root):
        self.path = Path(root) / "notify" / "deferral-owner-pacing.json"
        try:
            self.previous = json.loads(self.path.read_text())
            if not isinstance(self.previous, dict):
                self.previous = {}
        except (OSError, ValueError):
            self.previous = {}
        self.current = {}

    def route(self, row, now, live, deliver):
        if not owner_window(row, now) or not live(row["assignee"]):
            return False
        key = [row.get("updated_at"), row.get("notes"), row.get("defer_until")]
        # Without a touch identity we cannot detect lack of item progress.
        touched = parse_stamp(row.get("updated_at"))
        if touched is None or touched > now:
            return False
        old = self.previous.get(row["id"], {})
        if not isinstance(old, dict) or old.get("key") != key:
            old = {}
        count = old.get("count", 0)
        count = min(count + 1, LIMIT) if type(count) is int and count >= 0 else LIMIT
        state = {"key": key, "count": count, "nudged": old.get("nudged") is True}
        self.current[row["id"]] = state
        if count >= LIMIT:
            return False
        if not state["nudged"]:
            try:
                sent = deliver(row["assignee"],
                               f"OWNER-PACING: {row['id']} short owner-set defer lapsed; "
                               "check CI/current gate and update the item. No gate released.")
            except Exception:
                sent = None
            if not sent:
                return False
            state["nudged"] = True
        return True

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(self.path, self.current)
