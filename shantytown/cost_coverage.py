"""Coverage of already-read closure metadata, never another token counter.

An observed transcript group does not prove that every session/cycle holding a
seed was measured. Until that census exists, complete seed cost stays UNKNOWN.
"""
from .cost_review import LIMITS


def completed(records, bead=None):
    scope = ('requested seed' if bead else 'seed records already read for this command')
    result = {'status': 'LIMITED', 'scope': scope,
              'completed_seeds': None, 'unknown_cost_seeds': None, 'unknown_cost_share': None,
              'whole_session_item_limit': LIMITS['items'], 'partitions_enabled': False,
              'global_completed_seed_coverage': 'UNKNOWN',
              'reason': 'No independent all-session/cycle census; observed token groups are partial evidence.'}
    if not isinstance(records, dict):
        return result
    selected = {bead: records[bead]} if bead in records else {} if bead else records
    if bead and not selected:
        return result
    statuses = {'open', 'in_progress', 'blocked', 'deferred', 'hooked', 'closed'}
    for identity, record in selected.items():
        if (not isinstance(identity, str) or not identity or not isinstance(record, dict)
                or record.get('id', identity) != identity or record.get('status') not in statuses):
            return result
    count = sum(r['status'] == 'closed' for r in selected.values())
    result.update(completed_seeds=count, unknown_cost_seeds=count,
                  unknown_cost_share=1.0 if count else None)
    return result


def describe(value):
    total, unknown, share = (value[k] for k in ('completed_seeds', 'unknown_cost_seeds', 'unknown_cost_share'))
    fraction = 'UNKNOWN' if share is None and total != 0 else 'n/a' if total == 0 else f'{share:.0%}'
    number = lambda n: 'UNKNOWN' if n is None else str(n)
    return (f"Complete token cost UNKNOWN: {number(unknown)}/{number(total)} completed seeds ({fraction}); "
            f"cohort: {value['scope']}. Whole sessions only, at most {value['whole_session_item_limit']} items; "
            'oversized sources are refused, not estimated. Global all-session/cycle coverage: UNKNOWN.')
