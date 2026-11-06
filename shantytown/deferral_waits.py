"""Keep asynchronous work on its event, with a reminder rather than a poll."""
from datetime import timedelta
import re

WAIT = re.compile(r"\b(?:ci|reviews?|merg(?:e[ds]?|ing)|install(?:ed|ing|ation)?)\b", re.I)


def validate(reason, dependency_reason, condition, deadline, now, *, window=False):
    from .deferrals import _CONDITION
    # A tool named "ci" or the installed: marker is an identifier, not prose
    # declaring a polling wait. Preserve marker-only mechanical deferrals.
    if condition.kind in ('pr-merged', 'ci-terminal'):
        if deadline is None or deadline - now < timedelta(hours=24):
            raise ValueError('forge event waits require a backstop of at least 24 hours')
        return
    prose = _CONDITION.sub("", reason)
    if window or not WAIT.search(prose + "\n" + dependency_reason):
        return
    # An hourly date-only CI wait kept re-serving the administrator without
    # any new evidence. A real appointment must opt in as a scheduled window.
    if condition.kind == "date" or deadline is None or deadline - now < timedelta(hours=24):
        raise ValueError(
            "CI/review/merge/install waits require an event resume_when "
            "(closed:, release:, installed: or a registered event:) and a backstop "
            "of at least 24 hours; use --window only for a real scheduled window")
