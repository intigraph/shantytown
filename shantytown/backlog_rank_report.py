"""Bounded graph-order observations, never admission or administrator pages.

# arming: library; the fleet-owner ranking sweep calls this behind the pickup flag.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path

from .ask_visibility import is_ask
from .backlog_rank import MAX_CANDIDATES, QUERY, ordinary
from .crew_rules import ask
from .deployment import deployment_default
from .deferrals import parse_stamp
from .files import write_json_atomic
from .priority_advisory import priority, workable
from .protocols import rank_order
from .quipu import resolve_server
from .sd import StoreProof

INTERVAL = 300
LEDGER = "backlog_rank_attempt.json"


def scope(ready, *, now=None):
    """Select a deterministic window; never claim its order covers omitted IDs."""
    now = now or datetime.now(timezone.utc)
    candidates = {}
    for row in ready:
        if (row.get("status") != "open" or row.get("assignee")
                or is_ask(row) or not workable(row) or not ordinary(row)):
            continue
        if row.get("defer_until"):
            until = parse_stamp(row["defer_until"])
            if until is None:
                raise ValueError("rank observation defer clock UNKNOWN")
            if until > now:
                continue
        ident = row.get("id")
        if (not isinstance(ident, str) or not ident
                or ident in candidates or type(row.get("priority")) is not int
                or not 0 <= row["priority"] <= 4
                or not isinstance(row.get("created_at"), str)):
            raise ValueError("rank observation candidate UNKNOWN")
        candidates[ident] = row
    ordered = sorted(candidates.values(), key=lambda r: (
        priority(r), *rank_order(r.get("rank"), r.get("due_at"), r.get("created_at")),
        r["id"]))
    return ordered[:MAX_CANDIDATES], len(ordered)


def observation(root, selected, total, proof, *, now, reader=None):
    """A lean snapshot plus query witnesses is read-only evidence, not a CAS."""
    if not selected:
        return "graph rank observation: 0 eligible ordinary unowned READY; no query or admission"
    if (not isinstance(proof, StoreProof) or not proof.graph or not proof.quipu_url
            or proof.quipu_url.rstrip("/") != resolve_server(root=root).rstrip("/")):
        raise ValueError("rank observation store identity UNKNOWN")
    params = {"board": proof.graph, "owner": "",
              "now": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")}
    by_id = {row["id"]: row for row in selected}
    params.update({f"id{i:02}": ident for i, ident in enumerate(sorted(by_id))})
    rows = (reader or ask)(root, QUERY, params, limit=MAX_CANDIDATES + 1, timeout=2)
    if not isinstance(rows, list) or len(rows) != len(by_id):
        raise ValueError("rank observation coverage UNKNOWN")
    seen, names = set(), []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("rank observation row UNKNOWN")
        ident = row.get("id")
        if (ident not in by_id or ident in seen
                or type(row.get("revision")) is not int or row["revision"] < 1
                or type(row.get("priority")) is not int
                or row.get("sampled_at") != params["now"]):
            raise ValueError("rank observation witness UNKNOWN")
        if any(row.get(field) != by_id[ident].get(field) for field in (
                "priority", "status", "assignee", "created_at", "due_at")):
            raise ValueError("rank observation snapshot changed")
        seen.add(ident)
        if len(names) < 5:
            names.append(f"{ident} P{row['priority']}")
    coverage = ("complete supplied READY scope" if len(selected) == total
                else "bounded window; remaining IDs not ranked")
    return (f"graph rank observation: {len(selected)}/{total} eligible ordinary unowned READY "
            f"({coverage}); query order: {', '.join(names)}; "
            "advisory only, no dispatch/admission or global-order claim")


def sweep(root, ready, store, *, log=print, reader=None, now=None):
    """At most one attempt per five minutes, including failed/UNKNOWN reads.

    The ledger is an attempt clock, not a successful-proof receipt. The caller
    isolates every error here from independently established P0 notifications.
    """
    if deployment_default(root, "SHANTY_BACKLOG_PICKUP") != "1":
        return
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("rank observation clock UNKNOWN")
    stamp = now.timestamp()
    path = Path(root) / "notify" / LEDGER
    try:
        previous = json.loads(path.read_text())
    except FileNotFoundError:
        previous = {}
    if not isinstance(previous, dict):
        raise ValueError("rank observation attempt clock UNKNOWN")
    if previous:
        at = previous.get("at")
        if type(at) not in (int, float) or not math.isfinite(at) or at > stamp:
            raise ValueError("rank observation attempt clock UNKNOWN")
        if stamp - at < INTERVAL:
            return
    selected, total = scope(ready, now=now)
    # Reserve the attempt BEFORE I/O; a crash or refusal never creates a poll loop.
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, {"at": stamp})
    proof = store() if selected else None
    log(observation(root, selected, total, proof, now=now, reader=reader))
