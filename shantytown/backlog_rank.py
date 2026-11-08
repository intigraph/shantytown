"""Consume graph-owned pickup order without changing ownership or priority.

# arming: library; stop/tend callers must retain their admission and custody checks.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .crew_rules import ask
from .priority_advisory import priority, workable

QUERY = "seeds_work_rank_v1"
MAX_CANDIDATES = 64


def ordered(root, candidates, *, owner, board, reader=None, now=None):
    """Reorder an exact candidate set using a fresh, bounded stored-query proof.

    The graph chooses order; it does not authorize dispatch. Unknown or changed
    witnesses raise before any caller can claim work. Candidate scope is bounded
    so a worker stop cannot become a whole-board hydration operation.
    """
    candidates = list(candidates)
    if not candidates:
        return []
    if len(candidates) > MAX_CANDIDATES:
        raise ValueError("pickup rank candidate budget reached")
    by_id = {}
    for row in candidates:
        ident, revision = row.get("id"), row.get("revision")
        if (not isinstance(ident, str) or not ident or ident in by_id
                or type(revision) is not int or revision < 1):
            raise ValueError("pickup candidate identity/revision UNKNOWN")
        by_id[ident] = row
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("pickup clock lacks timezone")
    params = {"board": board, "owner": owner,
              "now": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")}
    # Fixed indexed parameters, not interpolated SPARQL or arbitrary query text.
    params.update({f"id{i:02}": ident for i, ident in enumerate(sorted(by_id))})
    rows = (reader or ask)(root, QUERY, params, limit=MAX_CANDIDATES + 1, timeout=8)
    if not isinstance(rows, list) or len(rows) != len(by_id):
        raise ValueError("pickup rank coverage UNKNOWN")
    result, seen = [], set()
    for proof in rows:
        ident = proof.get("id")
        if ident not in by_id or ident in seen:
            raise ValueError("pickup rank identity UNKNOWN")
        original = by_id[ident]
        # An order cannot launder changed priority/status/owner into admission.
        for field in ("revision", "priority", "status", "assignee", "created_at", "due_at"):
            if proof.get(field) != original.get(field):
                raise ValueError("pickup rank witness changed")
        if proof.get("sampled_at") != params["now"]:
            raise ValueError("pickup rank freshness UNKNOWN")
        seen.add(ident)
        result.append(original)
    return result


def next_after_anchor(root, ready, mine, *, owner, board, read_current,
                      claim, admit, reader=None, now=None):
    """Choose at a completed-anchor boundary; never preempt active work.

    Caller owns the stop/session/background/custody barriers. A claim callback
    must use the observed revision and verify the committed owner. A proven
    conflict retains the old queue; an indeterminate write raises and ends this
    pickup attempt rather than feeding a competing item.
    """
    if not mine:
        return None, False
    baseline = mine[0]
    higher = [row for row in ready
              if row.get("status") == "open" and not row.get("assignee")
              and workable(row) and priority(row) is not None
              and priority(baseline) is not None
              and priority(row) < priority(baseline)]
    candidates = {row["id"]: row for row in [*mine, *higher]}
    if len(candidates) > MAX_CANDIDATES:
        raise ValueError("pickup rank candidate budget reached")
    fresh = [read_current(ident) for ident in candidates]
    clock = now or datetime.now(timezone.utc)
    for row in fresh:
        previous = candidates.get(row.get("id"))
        if (previous is None or row.get("status") != "open"
                or row.get("priority") != previous.get("priority")
                or row.get("assignee") != previous.get("assignee")
                or not workable(row)):
            raise ValueError("pickup candidate changed before ranking")
        if row.get("defer_until"):
            until = datetime.fromisoformat(row["defer_until"].replace("Z", "+00:00"))
            if until.tzinfo is None or until > clock:
                raise ValueError("pickup candidate held or defer clock UNKNOWN")
    ranked = ordered(root, fresh, owner=owner, board=board, reader=reader, now=now)
    admitted = admit(ranked)
    if not admitted:
        return None, False
    best = admitted[0]
    if best.get("assignee"):
        # Only the caller's existing queue can contribute an owned candidate.
        if best["id"] not in {row["id"] for row in mine}:
            raise ValueError("pickup cannot take another owner's item")
        return best, False
    if claim(best, owner):
        return best, True
    fallback = admit([baseline])
    return (fallback[0] if fallback else None), False
