"""Selected Seeds producer seam for the shared reminder schedule.

This does not send messages. Unknown reconciliation attempts stay fenced until
operator reconciliation; event/receipt reads remain available. ACKs are read
back exactly before being reported accepted, and may be retried byte-identically
only after an exact readable null receipt.
"""
from __future__ import annotations

import json
from pathlib import Path

from .answer import Answer
from .files import write_json_atomic


class UnlockReader:
    def __init__(self, tracker, root):
        self.tracker = tracker
        self.path = Path(root) / "notify" / "unlock-reconcile.json"

    def events(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        state = json.loads(self.path.read_text()) if self.path.exists() else {"unknown":False}
        if state != {"unknown":False} and state != {"unknown":True}:
            raise ValueError("invalid unlock reconciliation fence")
        if not state["unknown"]:
            write_json_atomic(self.path, {"unknown":True})
            self.tracker.reconcile_blockers()
            write_json_atomic(self.path, {"unknown":False})
        # Reads never promote UNKNOWN prerequisites: only retained producer events
        # are eligible. An unknown write never authorizes another reconciliation.
        return self.tracker.unlock_events()

    def ack(self, identifier, event, receipt, *, attempted=False):
        current = self.tracker.unlock_receipt(identifier,event)
        if current == receipt:
            return True
        if current is not None:
            raise ValueError("conflicting unlock receipt")
        # Exact read proved null before any write/retry of this same ACK.
        self.tracker.ack_unlock(identifier,event,receipt)
        return self.tracker.unlock_receipt(identifier,event) == receipt
