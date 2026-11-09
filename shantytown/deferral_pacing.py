"""Owner pacing changes the reminder recipient, never the resume gate."""
import json
import hashlib
from pathlib import Path

from .ask_visibility import is_ask
from .deferrals import parse_stamp
from .deferral_notes import PROVENANCE_PREFIX as PREFIX, provenance, parse_provenance
from .files import write_json_atomic

def owner_window(row, now, *, event_ready=False):
    """Validate the legacy setter envelope; notification routing is independent."""
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
    """Notification custody is owner-first; it never grants resume authority.

    Old or ambiguous defer provenance still prevents release. It must not make
    ordinary deadline/event notifications administrator work by itself.
    """
    def __init__(self, root):
        self.path = Path(root) / "notify" / "deferral-owner-pacing.json"
        try:
            self.previous = json.loads(self.path.read_text())
            if not isinstance(self.previous, dict):
                self.previous = {}
        except (OSError, ValueError):
            self.previous = {}
        self.current = {}

    def route(self, row, finding, live, deliver, lead_for, *, observe=None):
        # Diagnostics must never consume a reminder or change its recipient.
        def report(recipient, role, outcome, error=None):
            if observe is not None:
                try:
                    observe(dict(recipient=recipient, role=role, outcome=outcome,
                                 exception_type=type(error).__name__[:64] if error else None))
                except Exception:
                    pass

        key = hashlib.sha256(json.dumps(
            [finding.key(), row.get("updated_at"), row.get("defer_until")],
            sort_keys=True).encode()).hexdigest()
        old = self.previous.get(row["id"], {})
        if not isinstance(old, dict) or old.get("key") != key:
            old = {}
        history = old.get("recipients", [])
        notified = ({name for name in history if isinstance(name, str) and name}
                    if isinstance(history, list) else set())
        # Migrate the single-recipient ledger without forgetting its receipt.
        if (old.get("nudged") is True
                and isinstance(old.get("recipient"), str) and old["recipient"]):
            notified.add(old["recipient"])
        state = {"key": key, "recipients": sorted(notified)}
        # Preserve receipts even while every route is temporarily unreachable.
        self.current[row["id"]] = state
        owner = row.get("assignee")
        recipients = [(owner, "owner")]
        lead = lead_for(owner)
        if lead and lead != owner:
            recipients.append((lead, "lead"))
        for recipient, reason in recipients:
            if not recipient:
                report(recipient, reason, "recipient-absent")
                continue
            if not live(recipient):
                report(recipient, reason, "live-absence")
                continue
            if recipient in notified:
                report(recipient, reason, "suppressed")
                return recipient, reason, "suppressed"
            try:
                sent = deliver(recipient,
                               f"OWNER-PACING: {row['id']} deferred work "
                               + ("event is ready" if finding.met or finding.prose_gate else "backstop lapsed")
                               + "; check the current gate and update the item. No gate released.")
            except Exception as error:
                report(recipient, reason, "send-failure", error)
                sent = None
            else:
                report(recipient, reason, "delivered" if sent else "send-unconfirmed")
            if sent:
                notified.add(recipient)
                state["recipients"] = sorted(notified)
                return recipient, reason, "delivered"
        return None, "owner-lead-unreachable", "pending"

    def save(self, preserve=()):
        self.current.update({key: self.previous[key] for key in preserve
                             if key in self.previous and key not in self.current})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(self.path, self.current)
