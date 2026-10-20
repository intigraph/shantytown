"""Recent deferred work occupies automatic-feed capacity, not a live pane."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import re

from .inbox import is_anchor, is_decision, is_message
from .plate_capacity import owner_name

SHORT_GATE_MINUTES = 60
EXTERNAL_GATE_HOURS = 24


def utc_now():
    return datetime.now(timezone.utc)


def _instant(value):
    if not isinstance(value, str):
        raise ValueError("defer_until is not a date")
    date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if date.tzinfo is None:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("defer_until timezone UNKNOWN")
        date = date.replace(tzinfo=timezone.utc)
    return date.astimezone(timezone.utc)


def rows(root, reg, owners):
    """A batch of metadata for only the mechanically idle candidate owners.

    Native Seeds never falls back to full SDK hydration. Configured legacy
    transports retain their owner-scoped reader; an unconfigured old bd
    deployment retains its existing feed behavior.
    """
    from .deployment import deployment_default
    from .files import FilesTracker
    from . import plate_capacity
    from .sd import SdTracker
    backend = deployment_default(root, "SHANTY_BACKEND")
    if backend is None or backend == "forgejo":
        return []
    if backend == "files":
        tracker = FilesTracker(root / "items")
    elif backend in {"seeds", "beads", "br"}:
        from .feed_check import _br_tracker
        tracker = _br_tracker(root, reg)
        if isinstance(tracker, SdTracker) and tracker._use_remote_projection():
            from .seeds_plate import owner_rows
            return owner_rows(
                tracker.prove_store(), None, plate_owners=tuple(owners),
                capacity=True, include_deferred=True, timeout=tracker.timeout).exact()
        if backend == "seeds":
            raise ValueError("native waiting-work metadata unavailable")
    else:
        raise ValueError("waiting-work backend UNKNOWN")
    found = {}
    for owner in owners:
        for row in plate_capacity.rows(tracker, owner):
            if owner_name(row.get("assignee")) == owner_name(owner):
                found[owner_name(owner), row["id"]] = row
    return list(found.values())


def from_rows(values, owners, *, now=None, minutes=SHORT_GATE_MINUTES):
    now = utc_now() if now is None else now
    if now.tzinfo is None or minutes <= 0:
        raise ValueError("waiting-work observation requires a UTC clock and positive window")
    owners = {owner_name(name) for name in owners}
    waiting, immediate = set(), set()
    window = timedelta(minutes=minutes)
    for row in values:
        owner = owner_name(row.get("assignee"))
        if owner not in owners:
            raise ValueError("waiting-work owner scope mismatch")
        status = row.get("status")
        if status not in {"open", "hooked", "in_progress", "blocked", "deferred",
                          "closed", "tombstone"}:
            raise ValueError("waiting-work status UNKNOWN")
        title = row.get("title")
        if not isinstance(title, str):
            raise ValueError("waiting-work title UNKNOWN")
        if (status in {"closed", "tombstone"} or is_message(title)
                or is_anchor(row.get("labels")) or is_decision(row.get("labels"))):
            continue
        date = row.get("defer_until")
        until = None if date in (None, "") else _instant(date)
        labels = row.get("labels") or []
        if not isinstance(labels, list) or any(not isinstance(label, str) for label in labels):
            raise ValueError("waiting-work labels UNKNOWN")
        if "blocked:external" in {label.strip().lower() for label in labels}:
            # Extend the existing shared selector, never add another feed gate.
            if (not isinstance(date, str) or "T" not in date
                    or not date.endswith(("Z", "+00:00")) or until is None):
                raise ValueError("external waiting-work UTC review time UNKNOWN")
            if timedelta(0) < until - now <= timedelta(hours=EXTERNAL_GATE_HOURS):
                waiting.add(owner)
            elif status in {"open", "hooked", "in_progress"} and until <= now:
                immediate.add(owner)
            continue  # Expired gates re-evaluate; this never opens an item.
        # Existing ready/active work must still reach the owner's haul. This
        # filter addresses a plate whose available work is all on gates.
        if status in {"open", "hooked", "in_progress"} and (
                until is None or until <= now):
            immediate.add(owner)
        elif until is not None and -window <= until - now <= window:
            waiting.add(owner)
    return waiting - immediate


def workers(root, reg, owners):
    if root is None or not owners:
        return set()
    return from_rows(rows(root, reg, owners), owners)
