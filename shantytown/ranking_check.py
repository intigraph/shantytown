"""Advisory administrator ranking digest; never dispatch or reassign.

# arming: library; fleet-owner tend sweep calls this after supervision.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import time
from pathlib import Path

from . import crew_rules
from .deployment import deployment_default
from .inbox import is_message
from .priority_advisory import priority, workable
from .protocols import plate_key, rank_order


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
    unowned = list({r["id"]: r for r in ready
                    if not r.get("assignee") and workable(r)}.values())
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
            by_priority = {}
            for row in higher:
                q = priority(row)
                by_priority[q] = by_priority.get(q, 0) + 1
            summary = (f"{len(higher)} unowned P{next(iter(by_priority))} READY"
                       if len(by_priority) == 1 else
                       f"{len(higher)} unowned READY (" + ", ".join(
                           f"{n} P{q}" for q, n in sorted(by_priority.items())) + ")")
            mismatches.append(f"{card.name}: {current['id']} P{priority(current)} < {summary}")
    lines += mismatches or ["no proven live-agent priority mismatch"]
    # One bounded witness list for the whole digest. Non-READY unowned P0
    # work remains actionable, but is labelled rather than presented as READY.
    p0_ids = set(p0)
    witnesses = {r["id"]: r for r in rows if r["id"] in p0_ids}
    witnesses.update({r["id"]: r for r in unowned})
    ordered = sorted(witnesses.values(), key=lambda r: (
        priority(r) if priority(r) is not None else math.inf,
        *rank_order(r.get("rank"), r.get("due_at"), r.get("created_at")), r["id"]))
    names = ", ".join(f"{r['id']} P{priority(r) if priority(r) is not None else '?'}"
                      + (" (not READY)" if r["id"] not in ready_ids else "")
                      for r in ordered[:5])
    if len(ordered) > 5:
        names += f", +{len(ordered) - 5} more"
    lines.append(f"unowned: {len(unowned)} READY; {len(p0)} P0 active; "
                 + (names or "none in complete active snapshot"))
    lines.append(counts)
    # Only an unowned P0 interrupts the administrator (Stiwi 2026-11-04: the
    # per-worker mismatch digest was "way too verbose"). Mismatches stay in the
    # tend log as an advisory; they are not a page.
    return "\n".join(lines), bool(p0)


def report(root, ready, rows, reg, panes, *, counts_reader=None):
    cards = reg.all().exact()
    live = {c.name for c in cards if c.pane and panes.exists(c.pane)}
    try:
        counts = (counts_reader or cohorts)(root)
    except Exception:
        counts = "P0 created/closed 7-day counts UNKNOWN"
    text, actionable = digest(ready, rows, cards, live, counts=counts)
    # Unknown counts are logged, not paged: an unreadable board metric is not an
    # unowned P0 (Stiwi 2026-11-04, ranking digest noise).
    return text, hashlib.sha256(text.encode()).hexdigest(), actionable


def sweep(root, reg, panes, *, snapshot, log=print, counts_reader=None, push=None,
          label_item=None):
    """Reuse the existing administrator notifier and changed-digest ledger."""
    try:
        ready, rows = snapshot()
        if label_item is not None:
            from .work_class import preferred_labels
            import time
            deadline, labelled = time.monotonic() + 20, 0
            # Candidate metadata only selects exact IDs. The callback reads
            # current labels, appends individually, and verifies each write.
            for row in ready:
                if labelled >= 3 or time.monotonic() >= deadline:
                    break
                if workable(row) and preferred_labels(row.get('labels')):
                    try:
                        label_item(row['id'])
                        labelled += 1
                    except Exception as exc:
                        log(f"ranking preference UNKNOWN {row['id']} ({type(exc).__name__}); no blind retry")
                        break
        text, key, actionable = report(root, ready, rows, reg, panes, counts_reader=counts_reader)
        _log_digest(root, text, key, log)
        try:
            from .backlog_hygiene import stale_review
            hygiene = stale_review(ready)
            # A separate log ledger cannot change the P0 page text or its key.
            if hygiene is not None or (Path(root) / "notify/backlog_hygiene_log.json").exists():
                hygiene = hygiene or "stale-work review: no eligible records in supplied READY scope"
                _log_digest(root, hygiene, hashlib.sha256(hygiene.encode()).hexdigest(), log,
                            ledger="backlog_hygiene_log.json")
        except Exception as exc:
            # Review metadata or its local ledger is not an admission gate for
            # independently established P0 advice. Preserve UNKNOWN separately.
            log(f"stale-work review UNKNOWN ({type(exc).__name__}); no lifecycle action")
        from .creel_advisory import Advice, Alerter
        return Alerter(root, reg, panes, push=push, filename="role_ranking.json",
                       label="administrator ranking").sweep(
                           {"fleet": Advice(text if actionable else
                               "ranking check recorded in tend log; no unowned P0 in complete active snapshot",
                               key, failure=actionable, risk=2)})
    except Exception as exc:
        log(f"ranking check UNKNOWN ({type(exc).__name__}); no auto-reassignment")
        return []


def _log_digest(root, text, key, log, *, ledger="role_ranking_log.json"):
    """Changed content logs immediately; an unchanged digest at most hourly.

    This ledger controls only verbose tend output. Alerter still owns paging,
    including retrying a failed push and preserving the P0-only risk contract.
    """
    path = Path(root) / "notify" / ledger
    try:
        previous = json.loads(path.read_text())
        if not isinstance(previous, dict):
            previous = {}
    except (OSError, ValueError):
        previous = {}
    now = time.time()
    at = previous.get("at")
    if (previous.get("key") == key and type(at) in (int, float)
            and math.isfinite(at) and 0 <= now - at < 3600):
        return
    log(text)
    try:
        from .files import write_json_atomic
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(path, dict(key=key, at=now))
    except OSError as exc:
        log(f"ranking log dedupe UNKNOWN ({type(exc).__name__}); paging unchanged")
