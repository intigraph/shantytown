"""ASK-class items stay visible; only Stiwi records Brief's Later choice."""
from collections.abc import Mapping

ASK_LABELS = frozenset({'needs-stiwi', 'blocked:human', 'desk', 'decision-needed', 'decision-stiwi'})
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
    prospective = _fields(item) | changes
    deferring = changes.get('status') == 'deferred' or bool(changes.get('defer_until'))
    # Classification changes must not strand a newly recognised ASK on an
    # already deferred item. Reopening in the same request remains safe.
    classifying_deferred = (prospective.get('status') == 'deferred'
                            and bool({'labels', 'title', 'blocker_kind'} & changes.keys())
                            and (is_ask(prospective)
                                 or changes.get('blocker_kind') == 'blocked:human'))
    if not deferring and not classifying_deferred:
        return
    if (is_ask(item) or is_ask(prospective)
            or changes.get('blocker_kind') == 'blocked:human'):
        raise ValueError(REFUSAL)
