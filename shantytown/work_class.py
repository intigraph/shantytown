"""Work-lane eligibility from an authoritative item read (aegis-x1q).

Callers must supply the exact tracker item, never a ready-list/caller snapshot.
The Quipu-specific class label is authoritative; no repository field or title
inference is involved (Wu's 87ix ruling).
"""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from . import harness


def claude_work_class(item) -> tuple[bool, str]:
    labels = getattr(item, "labels", None)
    if not isinstance(labels, (tuple, list, set, frozenset)) or not all(
            isinstance(label, str) for label in labels):
        return False, "work-class labels are missing or unreadable"
    if "work:design" in labels:
        return True, "authoritative work:design label"
    if "work:important-quipu-code" not in labels:
        return False, "no admitted work-class label"
    return True, "authoritative work:important-quipu-code label"


def exempt(card, policy) -> bool:
    """A configured lead exemption concerns only this filter, never a budget."""
    return (card.role in ("lead", "administrator")
            and card.name in policy.class_exempt)


def lane_refusal(item, actual, agent=None) -> str:
    eligible, reason = claude_work_class(item)
    wanted = "claude" if eligible else "codex"
    if actual == wanted:
        return ""
    if actual == "claude":
        return ("claude lane admits designs and important Quipu code only "
                f"(aegis-x1q); dispatch to codex: {reason}")
    return (f"work class requires {wanted}, but explicit target {agent} uses "
            f"{actual}: {reason} (aegis-x1q); target and harness unchanged")


def for_card(verdict, policy, card, root=None):
    """Attach lane eligibility without replacing any prior usage/hold verdict."""
    return replace(verdict, admit_class=policy.admit_class,
                   work_harness=harness.name_for(card, root=root),
                   class_exempt=(card.name,) if exempt(card, policy) else ())


def read_item(root, item):
    """Feed rows select IDs only; an exact normal tracker read supplies class.

    A failed class read is ordinary, never a caller's claimed design permission.
    Priority remains available for the already-existing floor to run first.
    """
    from .cli import _raw_tracker
    try:
        current = _raw_tracker(SimpleNamespace(root=root)).get(item.id)
        if current.id != item.id:
            raise ValueError("item identity mismatch")
        return current
    except Exception:
        return SimpleNamespace(id=item.id, priority=getattr(item, "priority", None),
                               labels=None)


