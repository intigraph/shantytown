"""Due-date reminders on the existing fleet-tend schedule (aegis-873).

Reads are bounded projections. Delivery intent is written before sending; a
stable inbox receipt marker reconciles unknown writes without duplicate sends.
A complete healthy read rearms resolved/re-dated episodes. UNKNOWN preserves
state and sends nothing. One digest per recipient per pass, then at most daily.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import fcntl

from .files import write_json_atomic
from .inbox import is_message


def instant(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def findings(rows, now):
    result = []
    seen = set()
    for row in rows:
        if row.get("status") not in ("open", "in_progress", "blocked"):
            continue
        if is_message(row.get("title", "")) or any(str(label).lower() == "inbox" for label in (row.get("labels") or [])):
            continue
        identifier, due = row.get("id"), row.get("due_at")
        if not isinstance(identifier, str) or not identifier or identifier in seen:
            raise ValueError("overdue row identity missing or duplicated")
        seen.add(identifier)
        if not due:
            continue
        if instant(due) < now:
            result.append(row)
    return result


class OverdueAlerter:
    def __init__(self, root, reg, *, read, deliver, events=None, receipt=None, now=None, log=None):
        self.root, self.reg = Path(root), reg
        self.receipt = receipt
        self.events = events
        self.read, self.deliver = read, deliver
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.log = log or (lambda message: None)
        self.path = self.root / "notify" / "overdue.json"

    def sweep(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.path.with_suffix(".lock").open("a") as held:
                try:
                    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return []
                return self._sweep()
        except Exception as error:
            self.log(f"overdue: UNKNOWN ({type(error).__name__}); no repeat delivery")
            return []

    def _sweep(self):
        from .tier import find_administrator
        now = self.now()
        rows = self.read().exact()
        current = findings(rows, now)
        events = self.events().exact() if self.events is not None else []
        # One shared notifier; 8iq supplies condition events, not a sender.
        for event in events:
            if (not isinstance(event,dict) or event.get("kind") != "unlock"
                    or not all(isinstance(event.get(k),str) and event[k] for k in ("id","episode"))
                    or (event.get("recipient") is not None and not isinstance(event["recipient"],str))):
                raise ValueError("invalid unlock reminder event")
            current.append({"id":event["id"],"due_at":event["episode"],
                            "assignee":event["recipient"],"kind":"unlock"})
        # Corruption is UNKNOWN, not an empty ledger authorizing repeat wakes.
        ledger = json.loads(self.path.read_text()) if self.path.exists() else {"entries": {}, "pending": {}}
        if not isinstance(ledger, dict) or set(ledger) != {"entries", "pending"}:
            raise ValueError("invalid overdue ledger")
        entries, pending = ledger["entries"], ledger["pending"]
        if not isinstance(entries, dict) or not isinstance(pending, dict):
            raise ValueError("invalid overdue ledger entries")
        if len(entries) > 10000:
            raise ValueError("unlock receipt retention budget reached; review compaction before delivery")
        grouped = {}
        live_keys = set()
        for row in current:
            recipient = row.get("assignee") or find_administrator(self.reg)
            if not recipient:
                self.log(f"overdue: {row['id']} recipient UNKNOWN")
                continue
            self.reg.get(recipient)  # Unknown owner must not silently reroute.
            kind = row.get("kind", "overdue")
            key = json.dumps([kind,row["id"], row["due_at"], recipient], separators=(",", ":"))
            if key in live_keys:
                raise ValueError("duplicate reminder episode")
            live_keys.add(key)
            previous = entries.get(key)
            if previous is not None and (not isinstance(previous, (int,float)) or isinstance(previous,bool)):
                raise ValueError("invalid overdue delivery timestamp")
            if previous is None or (kind == "overdue" and now.timestamp() - previous >= 86400):
                grouped.setdefault(recipient, []).append((key, row["id"]))
        # Reconcile already attempted messages byte-for-byte before new work.
        sent = []
        for recipient, packet in list(pending.items()):
            already = self.receipt(recipient, packet["marker"]) if self.receipt is not None else False
            eligible = any(key in live_keys for key in packet["keys"])
            if not already and not eligible:
                if not any(json.loads(key)[0] == "unlock" for key in packet["keys"]):
                    del pending[recipient]
                    write_json_atomic(self.path, ledger)
                continue
            if already or self.deliver(recipient, packet["marker"], packet["body"]):
                for key in packet["keys"]:
                    if key in live_keys or json.loads(key)[0] == "unlock":
                        entries[key] = now.timestamp()
                del pending[recipient]
                sent.append(recipient)
                write_json_atomic(self.path, ledger)
        for recipient, candidates in sorted(grouped.items()):
            if recipient in pending or recipient in sent:
                continue
            keys = sorted(key for key, _ in candidates)
            digest = hashlib.sha256(json.dumps([keys,now.isoformat()]).encode()).hexdigest()[:24]
            marker = f"[overdue:{digest}]"
            ids = sorted(identifier for _,identifier in candidates)
            # Bound the durable title; complete recipient membership is in the
            # ledger packet, not lost when the visible preview is shortened.
            preview = ", ".join(ids[:5])[:150]
            overdue_count = sum(json.loads(key)[0] == "overdue" for key in keys)
            unlock_count = len(keys) - overdue_count
            body = (f"Work reminders ({overdue_count} overdue, {unlock_count} unlocked): {preview}. "
                    "Close, re-rank, or re-date with a reason. Full digest: notify/overdue.json.")
            packet = {"marker":marker,"body":body,"keys":keys}
            pending[recipient] = packet
            write_json_atomic(self.path, ledger)
            if self.deliver(recipient, marker, body):
                for key in keys:
                    entries[key] = now.timestamp()
                del pending[recipient]
                sent.append(recipient)
                write_json_atomic(self.path, ledger)
        ledger["entries"] = {key:value for key,value in entries.items()
                             if key in live_keys or json.loads(key)[0] == "unlock"}
        write_json_atomic(self.path, ledger)
        return sent
