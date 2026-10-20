"""Stopped-owner escalation, with a portable local lease/outbox floor.

# arming: library; stop/launch/capture hooks and the existing tend timer.

No agent polling, reassignment, launch or graph writes. Native Quipu lease expiry
and the Brief producer remain Unsupported until their governed adapters exist.
A lease expiry means missing heartbeat evidence, NOT proof of process death.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
from pathlib import Path
import re
import time
import uuid

from .files import write_json_atomic
from .inbox import is_message

GRACE = 300
LEASE = 1800
NATIVE_EXPIRY = "Unsupported: no admitted Quipu heartbeat/expiry contract"


def _time(value):
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError("invalid liveness time")
    return value


def _agent(name):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
        raise ValueError("invalid agent name")
    return name


class OwnedWork:
    def __init__(self, root):
        self.root = Path(root) / "owned-work"

    @contextmanager
    def locked(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.root / "lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            path = self.root / "state.json"
            data = json.loads(path.read_text()) if path.exists() else {}
            yield data
            write_json_atomic(path, data)

    def launch(self, agent, *, now=None):
        """Only a sanctioned launch clears an explicit stop (not a late hook)."""
        agent, now = _agent(agent), _time(time.time() if now is None else now)
        with self.locked() as data:
            data[agent] = dict(generation=uuid.uuid4().hex, state="live",
                               observed_at=now, expires_at=now + LEASE)

    def heartbeat(self, agent, *, now=None):
        agent, now = _agent(agent), _time(time.time() if now is None else now)
        with self.locked() as data:
            old = data.get(agent)
            if old and old["state"] in ("stopped", "ceiling"):
                return  # A delayed tool hook cannot undo an operator/ceiling stop.
            if old and now < old["observed_at"]:
                raise ValueError("heartbeat moved backwards")
            generation = old["generation"] if old else uuid.uuid4().hex
            data[agent] = dict(generation=generation, state="live",
                               observed_at=now, expires_at=now + LEASE)

    def stop(self, agent, *, at=None, reason="", ceiling=False, wake=False):
        agent, at = _agent(agent), _time(time.time() if at is None else at)
        with self.locked() as data:
            old = data.get(agent)
            if old and old["state"] in ("stopped", "ceiling"):
                if wake and old.get("notice") == "empty":
                    old.update(notice="pending", next_at=at)
                return  # Replaying/repeating a stop does not mint another event.
            data[agent] = dict(generation=(old or {}).get("generation", uuid.uuid4().hex),
                               state="ceiling" if ceiling else "stopped",
                               observed_at=at, expires_at=at, next_at=at,
                               reason=reason, notice="pending", event=uuid.uuid4().hex)

    def wake(self, agent, *, now=None):
        """A new input can invalidate an earlier empty queue, not a receipt."""
        agent, now = _agent(agent), _time(time.time() if now is None else now)
        with self.locked() as data:
            old = data.get(agent)
            if old and old.get("notice") == "empty":
                old.update(notice="pending", next_at=now)

    def snapshot(self):
        """Read-only local evidence for a future admitted Brief producer."""
        path = self.root / "state.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def tick(self, registry, rows_for, inbox, *, now=None, grace=GRACE, agents=None):
        """Serve only local pending deadlines. Complete owner reads, never board scans.

        The lock spans receipt lookup/delivery. Persist `attempting` BEFORE the
        remote write: after UNKNOWN, reconcile a receipt but never blindly resend.
        """
        now = _time(time.time() if now is None else now)
        if not math.isfinite(grace) or grace < 0:
            raise ValueError("invalid grace")
        result = []
        with self.locked() as data:
            for name, state in data.items():
                if agents is not None and name not in agents:
                    continue
                if state["state"] == "live":
                    if now < state["expires_at"]:
                        continue
                    state.update(state="expired", notice="pending",
                                 next_at=state["expires_at"], event=uuid.uuid4().hex, reason="heartbeat lease expired; process state UNKNOWN")
                if state.get("notice") in ("delivered", "empty") or now < state.get("next_at", 0):
                    continue
                marker = "stopped-owner:" + hashlib.sha256(
                    (name + ":" + state["event"]).encode()).hexdigest()
                if state.get("notice") in ("attempting", "unknown"):
                    # Recovery addresses the original recipient even if the
                    # current card/lead changed after an uncertain write.
                    receipt = inbox.find_delivery(state["recipient"], marker)
                    if receipt and receipt.body == state["body"]:
                        state.update(notice="delivered", receipt=receipt.id)
                        result.append((name, "reconciled"))
                    else:
                        state["notice"] = "unknown"
                        result.append((name, "delivery UNKNOWN; no resend"))
                    continue
                card = registry.get(name)
                recipient = state.get("recipient") or card.reports_to
                if not recipient or recipient == name:
                    administrators = [row.name for row in registry.all().exact()
                                      if row.role == "administrator"]
                    recipient = administrators[0] if len(administrators) == 1 else None
                if not recipient or recipient == name:
                    raise RuntimeError("stopped owner has no lead or unambiguous administrator")
                # A dangling lead is an orphan too; transport failure is not a
                # reason to route to a guessed administrator.
                try:
                    registry.get(recipient)
                except LookupError:
                    administrators = [row.name for row in registry.all().exact()
                                      if row.role == "administrator"]
                    recipient = administrators[0] if len(administrators) == 1 else None
                    if not recipient or recipient == name:
                        raise RuntimeError("stopped owner has no administrator")
                rows = rows_for(name).exact()
                if any(not isinstance(row, dict) or not row.get("id")
                       or type(row.get("priority")) is not int
                       or row["priority"] not in range(5) for row in rows):
                    raise ValueError("owned work metadata is unproven")
                owned = [dict(row) for row in rows if row.get("status") != "closed"
                         and (row.get("assignee") or "").split("/")[-1] == name
                         and not is_message(row.get("title", ""))]
                messages = inbox.unread(name)  # Pure read, never acknowledge/reroute content.
                # Parse actual instants. Lexical offsets are not due ordering.
                def urgent(row):
                    if row.get("priority") == 0:
                        return True
                    due = row.get("due_at")
                    if not due:
                        return False
                    stamp = datetime.fromisoformat(due.replace("Z", "+00:00"))
                    if stamp.tzinfo is None:
                        stamp = stamp.replace(tzinfo=timezone.utc)
                    return stamp.timestamp() <= now
                immediate = any(urgent(row) for row in owned)
                deadline = state["expires_at"] + grace
                if not immediate and now < deadline:
                    future_due = [datetime.fromisoformat(row["due_at"].replace("Z", "+00:00"))
                                  for row in owned if row.get("due_at")]
                    due_times = [(value if value.tzinfo else value.replace(tzinfo=timezone.utc))
                                 .timestamp() for value in future_due]
                    state["next_at"] = min([deadline] + due_times)
                    continue
                report = dict(agent=name, recipient=recipient, state=state["state"],
                              observed_at=state["observed_at"], expires_at=state["expires_at"],
                              measured_at=now, reason=state.get("reason", ""),
                              seeds=owned, unread_ids=[m.id for m in messages],
                              native_expiry=NATIVE_EXPIRY)
                if not owned and not messages:
                    state["notice"] = "empty"
                    continue
                report_path = self.root / (marker.split(":", 1)[1] + ".json")
                write_json_atomic(report_path, report)
                summary = "; ".join(f"{r['id']} P{r.get('priority', '?')} due={r.get('due_at') or '-'}"
                                    for r in owned)
                body = (f"{marker} {name} {state['state']}: {len(owned)} seed(s), "
                        f"{len(messages)} unread. {summary}. Lead: reassign via st go, repool, "
                        f"or hold with reason/resume condition. Report {report_path}")
                # Inbox is a pointer channel. Full, uncapped ownership snapshot
                # remains on disk; long lists do not cause repeated failed writes.
                if len(body.encode()) > 480:
                    body = (f"{marker} {name} {state['state']}: {len(owned)} seed(s), "
                            f"{len(messages)} unread; full report {report_path}. "
                            "Lead: reassign, repool, or hold with reason/resume condition.")
                if len(body.encode()) > 480:
                    raise ValueError("stopped-owner pointer exceeds inbox budget")
                state.update(notice="attempting", recipient=recipient, report=str(report_path), body=body)
                write_json_atomic(self.root / "state.json", data)
                try:
                    receipt = inbox.deliver(recipient, body, frm="st stopped-owner")
                    observed = inbox.find_delivery(recipient, marker)
                    if (observed is None or observed.id != receipt.id or observed.body != body):
                        raise RuntimeError("stopped-owner receipt read-back unproven")
                except Exception:
                    state["notice"] = "unknown"
                    write_json_atomic(self.root / "state.json", data)
                    raise
                state.update(notice="delivered", receipt=receipt.id)
                result.append((name, "delivered"))
        return result
