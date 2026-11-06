"""Resume best-effort tend work where the previous pass ran out of time.

Respawn precedes this schedule. A skipped sweep is unobserved, never a
successful sweep or a failed condition read. No in-flight work is interrupted.
"""
from __future__ import annotations

import json
from pathlib import Path

from .files import write_json_atomic


class SweepRotation:
    def __init__(self, root: Path, *, dry_run=False, log=lambda message: None):
        self.path = Path(root) / "notify" / "tend-sweep-rotation.json"
        self.dry_run = dry_run
        self.log = log
        self.cursor = None
        self.next_cursor = None
        self.waiting = False
        self.rotated = []
        self.started = []
        try:
            value = json.loads(self.path.read_text())
            cursor = value["next"]
            if value.get("version") != 1 or not (
                    cursor is None or isinstance(cursor, str)
                    and 0 < len(cursor) <= 128):
                raise ValueError("invalid rotation cursor")
            self.cursor = cursor
            self.waiting = cursor is not None
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, TypeError):
            self.log("sweep rotation state UNKNOWN; starting at the first sweep")

    @staticmethod
    def _cursor(label):
        # Child cycle work cannot be reached unless its parent reads requests.
        return "cycle-requests" if label.startswith("cycle:") else label

    def admission(self, label: str, *, within_budget: bool):
        """None admits work; rotation/budget means UNKNOWN with no invocation."""
        if self.waiting:
            if label != self.cursor:
                self.rotated.append(label)
                return "rotation"
            self.waiting = False
        if not within_budget:
            if self.next_cursor is None:
                self.next_cursor = self._cursor(label)
            return "budget"
        self.started.append(label)
        return None

    def finish(self):
        # A completed suffix wraps to the beginning NEXT pass. If an optional
        # cursor vanished, discard it rather than keeping the whole pass blind.
        if self.waiting:
            self.log("sweep rotation cursor absent this pass; resetting next pass")
        self.log("sweep rotation executed=" + ",".join(self.started)
                 + "; rotation-skipped=UNKNOWN:" + ",".join(self.rotated))
        if self.dry_run:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            write_json_atomic(self.path, {"version": 1, "next": self.next_cursor})
        except OSError as error:
            # A scheduling ledger failure cannot stop supervision or pretend
            # the next pass will use a cursor that was not durably stored.
            self.log(f"sweep rotation persistence UNKNOWN ({type(error).__name__})")
