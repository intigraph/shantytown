"""Selected Seeds producer seam for the shared reminder schedule.

This does not send messages. Unknown reconciliation attempts stay fenced until
operator reconciliation; event/receipt reads remain available. ACKs are read
back exactly before being reported accepted, and may be retried byte-identically
only after an exact readable null receipt.
"""
from __future__ import annotations

import json
import hashlib
from pathlib import Path

from .answer import Answer
from .files import write_json_atomic


class UnlockReader:
    def __init__(self, tracker, root, *, identifier=None):
        self.tracker = tracker
        self.identifier = identifier
        name = "unlock-reconcile.json"
        if identifier is not None:
            from .sd import SdTracker
            SdTracker._unlock_target(identifier)
            name = "unlock-reconcile-" + hashlib.sha256(identifier.encode()).hexdigest() + ".json"
        self.path = Path(root) / "notify" / name

    def events(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        state = json.loads(self.path.read_text()) if self.path.exists() else {"unknown":False}
        if state != {"unknown":False} and state != {"unknown":True}:
            raise ValueError("invalid unlock reconciliation fence")
        if not state["unknown"]:
            write_json_atomic(self.path, {"unknown":True})
            if self.identifier is None:
                self.tracker.reconcile_blockers()
            else:
                self.tracker.reconcile_blockers(self.identifier)
            write_json_atomic(self.path, {"unknown":False})
        # Reads never promote UNKNOWN prerequisites: only retained producer events
        # are eligible. An unknown write never authorizes another reconciliation.
        if self.identifier is None:
            return self.tracker.unlock_events()
        return self.tracker.unlock_events(self.identifier)

    def ack(self, identifier, event, receipt, *, attempted=False):
        if self.identifier is not None and identifier != self.identifier:
            raise ValueError("unlock ACK escaped reaction target")
        current = self.tracker.unlock_receipt(identifier,event)
        if current == receipt:
            return True
        if current is not None:
            raise ValueError("conflicting unlock receipt")
        # Exact read proved null before any write/retry of this same ACK.
        self.tracker.ack_unlock(identifier,event,receipt)
        return self.tracker.unlock_receipt(identifier,event) == receipt


def react(tracker, root, registry, identifier, *, deliver, receipt, log=None):
    """Finite reaction seam; deployment supplies the existing shared inbox adapters.

    No scheduler or sender is created here. The caller owns matching the Chaski
    firing and enabling the admitted runtime binding. SDK condition rechecks and
    the shared retained delivery ledger remain authoritative on every invocation.
    """
    from .overdue import OverdueAlerter
    reader = UnlockReader(tracker, root, identifier=identifier)
    return OverdueAlerter(root,registry,read=None,deliver=deliver,receipt=receipt,
                         events=reader.events,ack=reader.ack,log=log,
                         unlock_target=identifier).sweep()
