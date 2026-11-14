"""Keep asynchronous work on its event, with a reminder rather than a poll."""
from datetime import timedelta
import re

EXECUTION_WAIT = re.compile(r"\b(?:ci|reviews?|merg(?:e[ds]?|ing))\b", re.I)


def refuse_execution_wait(reason, dependency_reason, condition, *, window=False):
    """CI/review remains active work, not a reason to hide it for a day."""
    from .deferrals import _CONDITION
    prose = _CONDITION.sub("", reason)
    kind = getattr(condition, "kind", None)
    # Keep explicit calendar appointments, never an event wait disguised by
    # --window. The flag alone was enough to hide a pending CI job (vo3j).
    appointment = (window and kind == "date"
                   and re.search(r"\b(?:appointment|meeting)\b", prose, re.I)
                   and not re.search(r"\b(?:pending|wait(?:ing)?|blocked)\b", prose, re.I))
    if kind in ("ci-terminal", "pr-merged") or (
            not appointment and EXECUTION_WAIT.search(prose + "\n" + dependency_reason)):
        raise ValueError(
            "CI/review/merge wait: stay in_progress and record the exact wake "
            "on the item; do not date-defer work. Record real prerequisites "
            "as dependency edges instead. A backstop or --window does not waive this.")


WAIT = re.compile(r"\b(?:ci|reviews?|merg(?:e[ds]?|ing)|install(?:ed|ing|ation)?)\b", re.I)


def validate(reason, dependency_reason, condition, deadline, now, *, window=False):
    from .deferrals import _CONDITION
    # A tool named "ci" or the installed: marker is an identifier, not prose
    # declaring a polling wait. Preserve marker-only mechanical deferrals.
    if condition.kind in ('pr-merged', 'ci-terminal', 'ruling', 'activation',
                          'recurring-quiet', 'evidence-count'):
        if deadline is None or deadline - now < timedelta(hours=24):
            raise ValueError('registered event waits require a backstop of at least 24 hours')
        return
    prose = _CONDITION.sub("", reason)
    if window or not WAIT.search(prose + "\n" + dependency_reason):
        return
    # An hourly date-only CI wait kept re-serving the administrator without
    # any new evidence. A real appointment must opt in as a scheduled window.
    if condition.kind == "date" or deadline is None or deadline - now < timedelta(hours=24):
        raise ValueError(
            "CI/review/merge/install waits require an event resume_when "
            "(closed:, release:, installed:, cold-launch: or a registered event:) and a backstop "
            "of at least 24 hours; use --window only for a real scheduled window")
