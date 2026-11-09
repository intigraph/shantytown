"""Bounded stale-work review proposals; never lifecycle or priority writes.

# arming: library; the existing fleet-owner tend ranking sweep is the caller.
"""
from datetime import datetime, timedelta, timezone

from .ask_visibility import is_ask
from .backlog_rank import ordinary
from .priority_advisory import priority, workable

STALE_DAYS = 30
MAX_ROWS = 5000


def stale_review(ready, *, now=None):
    """Review only unowned ordinary READY P3/P4 in the supplied snapshot.

    dateModified is metadata freshness, not proof of no comments or dependents.
    The bounded ranking projection excludes inbox and most deferred cohorts;
    this result deliberately makes no claim about them or the whole backlog.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("stale review clock lacks timezone")
    rows = list(ready)
    if len(rows) > MAX_ROWS:
        raise ValueError("stale review snapshot exceeds coverage bound")
    selected, seen, unknown, eligible = [], set(), 0, 0
    for row in rows:
        ident = row.get("id")
        if not isinstance(ident, str) or not ident or ident in seen:
            raise ValueError("stale review identity UNKNOWN")
        seen.add(ident)
        if (row.get("status") != "open" or row.get("assignee")
                or priority(row) not in (3, 4) or is_ask(row)
                or not ordinary(row) or not workable(row)):
            continue
        eligible += 1
        value = row.get("updated_at")
        try:
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (AttributeError, TypeError, ValueError):
            unknown += 1
            continue
        if stamp.tzinfo is None or stamp > now:
            unknown += 1
            continue
        if stamp <= now - timedelta(days=STALE_DAYS):
            selected.append((stamp, ident))
    if not eligible:
        return None
    selected.sort()
    names = ", ".join(ident for _, ident in selected[:5]) or "none observed"
    if len(selected) > 5:
        names += f", +{len(selected) - 5} more"
    return (f"stale-work review (supplied READY scope only): {len(selected)} unowned P3/P4 "
            f"with metadata >= {STALE_DAYS} days old; {unknown} freshness UNKNOWN; {names}. "
            "Review comments, dependents, due dates and current custody before proposing "
            "close or renewal; no automatic closure. Inbox/deferred cull coverage not measured.")
