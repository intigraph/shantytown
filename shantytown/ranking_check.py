"""Advisory administrator ranking digest; never dispatch or reassign.

# arming: library; fleet-owner tend sweep calls this after supervision.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib

from . import crew_rules
from .deployment import deployment_default
from .inbox import is_message
from .priority_advisory import priority, workable
from .protocols import plate_key


def cohorts(root, *, now=None, reader=None):
    """Seven UTC calendar dates, including today; not an invented rolling window."""
    now = now or datetime.now(timezone.utc)
    end = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    start = end - timedelta(days=7)
    query = deployment_default(root, "SHANTY_BOARD_METRICS_QUERY") or "seeds_board_metrics_v1"
    rows = (reader or crew_rules.ask)(root, query, {
        "now": now.isoformat().replace("+00:00", "Z"),
        "day00": start.isoformat().replace("+00:00", "Z"),
        "day31": end.isoformat().replace("+00:00", "Z"),
    }, limit=2049, timeout=8)
    for metric in ("aggregation_control", "coverage"):
        controls = [r.get("value") for r in rows if r.get("metric") == metric]
        if len(controls) != 1 or type(controls[0]) is not int or controls[0] < 1:
            raise ValueError("board cohort coverage UNKNOWN")
    if any(r.get("invalid", 0) != 0 for r in rows):
        raise ValueError("board cohort integrity UNKNOWN")
    counts = {}
    for metric in ("created", "closed"):
        selected = [r for r in rows if r.get("metric") == metric]
        totals = [r["value"] for r in rows if r.get("metric") == metric + "_total"]
        if any(type(r.get("value")) is not int or r["value"] < 0 for r in selected):
            raise ValueError("invalid cohort count")
        if any(type(v) is not int or v < 0 for v in totals):
            raise ValueError("invalid cohort total")
        for row in selected:
            if (str(row.get("priority")) not in {"0", "1", "2", "3", "4"}
                    or row.get("kind") not in {"work", "inbox"}
                    or not isinstance(row.get("day"), str)
                    or not start.date().isoformat() <= row["day"] < end.date().isoformat()):
                raise ValueError("cohort dimensions UNKNOWN")
        if totals != ([sum(r["value"] for r in selected)] if selected else []):
            raise ValueError("cohort totals do not reconcile")
        counts[metric] = sum(r["value"] for r in selected
                             if str(r.get("priority")) == "0" and r.get("kind") == "work")
    return f"P0 work, 7 UTC dates {start.date()}..{(end-timedelta(days=1)).date()}: created {counts['created']}, closed {counts['closed']}"


def digest(ready, rows, cards, live, *, counts):
    """Every live agent's canonical plate witness; strict unowned READY comparisons."""
    unowned = [r for r in ready if not r.get("assignee") and workable(r)]
    p0 = sorted({r["id"] for r in rows if not r.get("assignee") and priority(r) == 0
                 and r.get("status") not in ("closed", "tombstone")
                 and not is_message(r.get("title", ""))
                 and "inbox" not in (r.get("labels") or [])})
    lines, mismatches = ["ranking check (advisory; no auto-reassignment)"], []
    ready_ids = {r["id"] for r in ready}
    for card in sorted(cards, key=lambda c: c.name):
        if card.name not in live:
            continue
        owned = [r for r in rows if (r.get("assignee") or "").split("/")[-1] == card.name
                 and r.get("status") in ("open", "in_progress", "hooked") and workable(r)]
        if not owned:
            continue
        current = min(owned, key=lambda r: plate_key(r.get("status"), priority(r), r["id"],
                         ready_ids, rank=r.get("rank"), due_at=r.get("due_at"), created_at=r.get("created_at")))
        higher = [r for r in unowned if priority(r) is not None and priority(current) is not None
                  and priority(r) < priority(current)]
        if higher:
            names = ", ".join(r["id"] for r in sorted(higher, key=lambda r: (priority(r), r["id"])))
            mismatches.append(f"{card.name}: {current['id']} P{priority(current)} below unowned READY {names}")
    lines += mismatches or ["no proven live-agent priority mismatch"]
    lines.append("unowned P0: " + (", ".join(p0) if p0 else "none in complete active snapshot"))
    lines.append(counts)
    return "\n".join(lines), bool(mismatches or p0)


def report(root, ready, rows, reg, panes, *, counts_reader=None):
    cards = reg.all().exact()
    live = {c.name for c in cards if c.pane and panes.exists(c.pane)}
    try:
        counts = (counts_reader or cohorts)(root)
    except Exception:
        counts = "P0 created/closed 7-day counts UNKNOWN"
    text, actionable = digest(ready, rows, cards, live, counts=counts)
    return text, hashlib.sha256(text.encode()).hexdigest(), actionable or "UNKNOWN" in counts


def sweep(root, reg, panes, *, snapshot, log=print, counts_reader=None, push=None):
    """Reuse the existing administrator notifier and changed-digest ledger."""
    try:
        ready, rows = snapshot()
        text, key, actionable = report(root, ready, rows, reg, panes, counts_reader=counts_reader)
        log(text)
        from .creel_advisory import Advice, Alerter
        return Alerter(root, reg, panes, push=push, filename="role_ranking.json",
                       label="administrator ranking").sweep(
                           {"fleet": Advice(text, key, failure=actionable, risk=2)})
    except Exception as exc:
        log(f"ranking check UNKNOWN ({type(exc).__name__}); no auto-reassignment")
        return []
