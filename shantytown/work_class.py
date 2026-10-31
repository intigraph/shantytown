"""Work-lane eligibility from an authoritative item read (aegis-x1q).

Callers must supply the exact tracker item, never a ready-list/caller snapshot.
Review status and class preferences come from exact labels; no repository field
or title inference is involved (Wu's 87ix ruling).
"""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from . import harness


def important_work_class(item) -> tuple[bool, str]:
    labels = getattr(item, "labels", None)
    if not isinstance(labels, (tuple, list, set, frozenset)) or not all(
            isinstance(label, str) for label in labels):
        return False, "work-class labels are missing or unreadable"
    if "work:design" in labels:
        return True, "authoritative work:design label"
    if "work:important-quipu-code" not in labels:
        return False, "no admitted work-class label"
    return True, "authoritative work:important-quipu-code label"


# Retain the historical internal name for callers inspecting class metadata.
# Classification is a routing preference, not an authoring restriction.
claude_work_class = important_work_class


def exempt(card, policy) -> bool:
    """Only a configured actual administrator receives a class exemption."""
    return card.role == "administrator" and card.name in policy.class_exempt


def authoring_class(item) -> bool:
    """An exemption needs readable authoring metadata, never an unknown review."""
    labels = getattr(item, "labels", None)
    readable = isinstance(labels, (tuple, list, set, frozenset)) and all(
        isinstance(label, str) for label in labels)
    return readable and "work:review" not in labels


def lane_refusal(item, actual, agent=None) -> str:
    if actual == "codex":
        return ""
    # Both harnesses author any class. An unreadable exact item cannot prove
    # that a Claude assignment is authoring rather than a Codex-only review.
    if actual == "claude":
        if authoring_class(item):
            return ""
        labels = getattr(item, "labels", None)
        reason = ("reviews require codex" if isinstance(labels, (tuple, list, set, frozenset))
                  and "work:review" in labels else "work-class labels are missing or unreadable")
    else:
        reason = "authoring requires claude or codex; reviews require codex"
    return (f"work class refuses explicit "
            f"target {agent} using {actual}: {reason} (aegis-x1q); "
            "target and harness unchanged")


def for_card(verdict, policy, card, root=None):
    """Attach lane eligibility without replacing any prior usage/hold verdict."""
    return replace(verdict, admit_class=policy.admit_class,
                   work_harness=harness.name_for(card, root=root),
                   class_exempt=(card.name,) if exempt(card, policy) else ())


def read_item(root, item):
    """Feed rows select IDs only; an exact normal tracker read supplies class.

    A failed class read cannot establish authoring rather than review.
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
