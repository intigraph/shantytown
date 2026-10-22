"""ASK-class items stay visible; only Stiwi records Brief's Later choice."""
from collections.abc import Mapping

ASK_LABELS = frozenset({'needs-stiwi', 'blocked:human', 'desk', 'decision-needed'})
REFUSAL = ('Stiwi bsf8: ASK-class items must stay visible and cannot be deferred; '
           "use Brief's Later choice, recorded by Stiwi, not by an agent")


def _fields(item):
    return dict(item) if isinstance(item, Mapping) else vars(item).copy()


def is_ask(item):
    value = _fields(item)
    labels = value.get('labels') or []
    if isinstance(labels, str):
        labels = labels.split(',')
    labels = {label.get('name', '') if isinstance(label, Mapping) else label for label in labels}
    return (bool(ASK_LABELS & labels)
            or str(value.get('title', '')).strip().startswith('ASK Stiwi'))


def refuse_deferral(item, changes):
    """Check before any staging write, also covering a new human blocker."""
    if changes.get('status') != 'deferred' and not changes.get('defer_until'):
        return
    prospective = _fields(item) | changes
    if (is_ask(item) or is_ask(prospective)
            or changes.get('blocker_kind') == 'blocked:human'):
        raise ValueError(REFUSAL)
