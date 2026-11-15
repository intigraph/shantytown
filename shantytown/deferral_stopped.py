"""Bound the interruption, not the stopped owner's retained P0 inventory."""
from collections import Counter


def inventory(findings):
    counts = Counter(f'P{f.priority}' if type(f.priority) is int and 0 <= f.priority <= 4
                     else 'UNKNOWN' for f in findings)
    return {'total': len(findings), 'counts': dict(counts),
            'p0': sorted(f.bead for f in findings if type(f.priority) is int and f.priority == 0),
            'urgent': sorted(f.bead for f in findings if f.read_error
                             or (f.condition and f.condition.kind in ('ruling', 'activation')))}


def report(owner, detail, path):
    counts = detail['counts']
    lines = [f"STOPPED-OWNER-PACING: owner={owner} total={detail['total']} "
             + ' '.join(f'{p}={counts.get(p, 0)}' for p in ('P0', 'P1', 'P2', 'P3', 'P4', 'UNKNOWN')),
             'Deliberately stopped; administrator disposition only. No gate released.',
             'P0: ' + (', '.join(detail['p0'][:64]) or 'none')]
    if len(detail['p0']) > 64:
        lines.append(f"{len(detail['p0']) - 64} more P0 items; full inventory: {path}")
    if detail['urgent']:
        lines.append('Read-error/authority findings: ' + ', '.join(detail['urgent'][:16]))
        if len(detail['urgent']) > 16:
            lines.append(f"{len(detail['urgent']) - 16} more urgent findings; full inventory: {path}")
    return '\n'.join(lines)
