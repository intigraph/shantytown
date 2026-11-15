"""One reviewer per seed, retained across PR heads and successors.

Uses a Seeds label and the native revision fence rather than a local PR cache.
No dispatch or review approval is implied by a reservation.
"""
from __future__ import annotations

import re

from .tracker_result import phase

PREFIX = "reviewer:"
NAME = re.compile(r"[a-z][a-z0-9_-]{0,63}")


def reviewer(row):
    labels = row.get("labels")
    if not isinstance(labels, list) or any(not isinstance(x, str) for x in labels):
        raise ValueError("review reservation labels UNKNOWN")
    values = [x[len(PREFIX):] for x in labels if x.startswith(PREFIX)]
    if len(values) > 1 or any(not NAME.fullmatch(x) for x in values):
        raise ValueError("review reservation contradictory or malformed")
    return values[0] if values else None


def command(args, tracker):
    from .sd import SdTracker
    if not isinstance(tracker, SdTracker):
        raise ValueError("review reservations require the configured Seeds backend")
    phase("READ")
    row = tracker.stranded_read(args.item)
    revision = getattr(args, "if_revision", None)
    if revision is not None and revision != row["revision"]:
        raise ValueError("expected seed revision changed; reread the seed")
    old = reviewer(row)
    selected = getattr(args, "reviewer", None)
    parent = getattr(args, "inherit_from", None)
    if getattr(args, "replace_reviewer", None) is not None and not (selected or parent):
        raise ValueError("replacement requires --reviewer or --inherit-from")
    if selected and parent:
        raise ValueError("choose --reviewer or --inherit-from")
    if parent:
        if parent == args.item:
            raise ValueError("a seed cannot inherit from itself")
        selected = reviewer(tracker.stranded_read(parent))
        if selected is None:
            raise ValueError("predecessor has no reviewer reservation")
    if not selected:
        return {"id": args.item, "reviewer": old, "result": "observed"}
    if not NAME.fullmatch(selected):
        raise ValueError("reviewer must be a concrete crew name")
    contributors = set(getattr(args, "contributor", None) or [])
    if row.get("assignee"):
        contributors.add(row["assignee"])
    if selected in contributors:
        raise ValueError("reserved reviewer is an author/contributor; explicit independent reassignment needed")
    expected = getattr(args, "replace_reviewer", None)
    if expected is not None and expected != old:
        raise ValueError("expected reviewer changed; reread the seed")
    if old and old != selected and expected != old:
        raise ValueError("seed already reserves " + old + "; name it with --replace-reviewer")
    if old == selected:
        return {"id": args.item, "reviewer": old, "result": "unchanged"}
    labels = [x for x in row["labels"] if not x.startswith(PREFIX)] + [PREFIX + selected]
    result = {"id": args.item, "reviewer": selected, "previous": old,
              "inherited_from": parent, "result": "planned"}
    if args.dry_run:
        return result
    body = (f"Reviewer reservation: {old or '(none)'} -> {selected}. "
            + (f"Inherited from {parent}. " if parent else "")
            + "Reservation follows this seed across PR heads; it is not a review verdict.")
    phase("SUBMIT")
    # The native CAS includes the audit comment. A refusal/timeout is never retried.
    tracker.update(args.item, set_labels=",".join(labels),
                   if_revision=row["revision"], transition_comment=body)
    phase("READBACK")
    after = tracker.stranded_read(args.item)
    if (reviewer(after) != selected or set(after["labels"]) != set(labels)
            or after["revision"] <= row["revision"]
            or not any(c.get("text") == body for c in after.get("comments", [])
                       if isinstance(c, dict))):
        raise RuntimeError("reservation write outcome UNKNOWN; read back before retrying")
    return result | {"result": "verified"}
