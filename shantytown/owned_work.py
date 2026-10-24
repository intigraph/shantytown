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
                               observed_at=now, expires_at=now + LEASE, launched_at=now)

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
                               observed_at=now, expires_at=now + LEASE,
                               launched_at=(old or {}).get("launched_at"))

    def stop(self, agent, *, at=None, reason="", ceiling=False, wake=False, generation=None):
        agent, at = _agent(agent), _time(time.time() if at is None else at)
        with self.locked() as data:
            old = data.get(agent)
            if generation is not None and (old or {}).get("generation", "") != generation:
                return  # A replay cannot end a different launch generation.
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

    def pending(self, *, now=None):
        """Fair local scheduling order; no remote reads or liveness inference."""
        now = _time(time.time() if now is None else now)
        states = self.snapshot()
        return sorted((name for name, state in states.items()
                       if (state["state"] == "live" and now >= state["expires_at"] or
                           state["state"] != "live" and
                           state.get("notice") not in ("delivered", "empty") and
                           now >= state.get("next_at", 0))),
                      key=lambda name: (states[name].get("attempted_at", 0), name))

    def attempted(self, agent):
        """Persist only fairness metadata before starting potentially slow I/O."""
        with self.locked() as data:
            if agent in data:
                data[agent]["attempted_at"] = 1 + max(
                    (state.get("attempted_at", 0) for state in data.values()), default=0)

    def _replace(self, agent, before, after):
        # Local compare-and-swap only. No remote callback may hold this lock:
        # tool heartbeat hooks must not wait for somebody else's slow inbox.
        with self.locked() as data:
            if data.get(agent) != before:
                return False
            data[agent] = after
        return True

    def _finish(self, agent, attempt, notice, receipt=None):
        with self.locked() as data:
            current = data.get(agent, {})
            if (current.get("event") != attempt["event"] or
                    current.get("generation") != attempt["generation"] or
                    current.get("notice") not in ("attempting", "unknown")):
                return False
            current.update(notice=notice)
            if receipt is not None:
                current["receipt"] = receipt.id
        return True

    def tick(self, registry, rows_for, inbox, *, now=None, grace=GRACE, agents=None):
        """Serve local deadlines with complete owner reads, never board scans.

        Reserve `attempting` atomically before delivery. Recovery reads the exact
        original receipt, never resends. A launch/heartbeat during metadata I/O
        invalidates the pending observation before any outbox reservation.
        """
        now = _time(time.time() if now is None else now)
        if not math.isfinite(grace) or grace < 0:
            raise ValueError("invalid grace")
        result = []
        for name, initial in self.snapshot().items():
            if agents is not None and name not in agents:
                continue
            state = dict(initial)
            if state["state"] == "live":
                if now < state["expires_at"]:
                    continue
                state.update(state="expired", notice="pending",
                             next_at=state["expires_at"], event=uuid.uuid4().hex,
                             reason="heartbeat lease expired; process state UNKNOWN")
                if not self._replace(name, initial, state):
                    continue
            if state.get("notice") in ("delivered", "empty") or now < state.get("next_at", 0):
                continue
            marker = "stopped-owner:" + hashlib.sha256(
                (name + ":" + state["event"]).encode()).hexdigest()
            if state.get("notice") in ("attempting", "unknown"):
                receipt = inbox.find_delivery(state["recipient"], marker)
                matched = receipt is not None and receipt.body == state["body"]
                if self._finish(name, state, "delivered" if matched else "unknown",
                                receipt if matched else None):
                    result.append((name, "reconciled" if matched else "delivery UNKNOWN; no resend"))
                continue
            card = registry.get(name)
            recipient = card.reports_to
            if not recipient or recipient == name:
                administrators = [row.name for row in registry.all().exact()
                                  if row.role == "administrator"]
                recipient = administrators[0] if len(administrators) == 1 else None
            if not recipient or recipient == name:
                raise RuntimeError("stopped owner has no lead or unambiguous administrator")
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
            messages = inbox.unread(name)  # Never acknowledge or copy message bodies.
            def due_at(row):
                due = row.get("due_at")
                if not due:
                    return None
                stamp = datetime.fromisoformat(due.replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
                return stamp.timestamp()
            dues = [value for row in owned if (value := due_at(row)) is not None]
            immediate = any(row["priority"] == 0 for row in owned) or any(t <= now for t in dues)
            deadline = state["expires_at"] + grace
            if not immediate and now < deadline:
                self._replace(name, state, dict(state, next_at=min([deadline] + dues)))
                continue
            if not owned and not messages:
                self._replace(name, state, dict(state, notice="empty"))
                continue
            report_path = self.root / (marker.split(":", 1)[1] + ".json")
            report = dict(agent=name, recipient=recipient, state=state["state"],
                          observed_at=state["observed_at"], expires_at=state["expires_at"],
                          measured_at=now, reason=state.get("reason", ""),
                          seeds=owned, unread_ids=[m.id for m in messages],
                          native_expiry=NATIVE_EXPIRY)
            summary = "; ".join(f"{r['id']} P{r['priority']} due={r.get('due_at') or '-'}" for r in owned)
            body = (f"{marker} {name} {state['state']}: {len(owned)} seed(s), "
                    f"{len(messages)} unread. {summary}. Lead: reassign via st go, repool, "
                    f"or hold with reason/resume condition. Report {report_path}")
            if len(body.encode()) > 480:
                body = (f"{marker} {name} {state['state']}: {len(owned)} seed(s), "
                        f"{len(messages)} unread; full report {report_path}. "
                        "Lead: reassign, repool, or hold with reason/resume condition.")
            if len(body.encode()) > 480:
                raise ValueError("stopped-owner pointer exceeds inbox budget")
            attempt = dict(state, notice="attempting", recipient=recipient,
                           report=str(report_path), body=body)
            if not self._replace(name, state, attempt):
                continue  # A restart, heartbeat or another consumer won the race.
            try:
                write_json_atomic(report_path, report)
                receipt = inbox.deliver(recipient, body, frm="st stopped-owner")
                observed = inbox.find_delivery(recipient, marker)
                if observed is None or observed.id != receipt.id or observed.body != body:
                    raise RuntimeError("stopped-owner receipt read-back unproven")
            except Exception:
                self._finish(name, attempt, "unknown")
                raise
            self._finish(name, attempt, "delivered", receipt)
            result.append((name, "delivered"))
        return result
