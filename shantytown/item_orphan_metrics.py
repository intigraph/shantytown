"""Report the existing sweep's item evidence; no new board query or detector."""
import math
from pathlib import Path

from .duties import _read
from .files import write_json_atomic
from .stranded_work import eligible, owner, release_threshold, resume_exempt


def invalidate(root, now):
    path = Path(root) / 'stranded-work/orphans.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, dict(checked_at=now, complete=False, orphaned=0))


def record(root, rows, findings, results, *, observe, cards, now):
    """Count only fresh positive evidence; successful CAS readback wins.

    An unknown/conflicted release or changed owner generation cannot certify
    a count. A stale projection is never queried again by this reporter.
    """
    active = [row for row in rows if eligible(row, operator_stopped=True)]
    released = {ident for ident, state in results
                if state in {'release released', 'release reconciled: released'}}
    complete = all(type(row.get('priority')) is int and row['priority'] in range(5)
                   and isinstance(row.get('labels') or [], list) for row in rows)
    report = dict(checked_at=now, complete=complete, orphaned=0)
    observations, thresholds = {}, {}
    try:
        for row in active:
            if row['id'] in released:
                continue
            name = owner(row)
            if name not in observations:
                observations[name] = observe(name, cards.get(name))
                thresholds[name] = release_threshold(active, name)
            evidence = observations[name]
            state = evidence.get('state')
            if state == 'live':
                continue
            if state not in {'operator-stopped', 'down', 'missing', 'cycle-blocked'}:
                report['complete'] = False
                continue
            if state != 'operator-stopped' and (evidence.get('intentional_stop') is True
                                               or resume_exempt(evidence.get('resume_at'), now)):
                continue
            entry = findings.get(row['id'], {})
            since = entry.get('down_since')
            if (entry.get('checked_at') != now or entry.get('owner') != name
                    or entry.get('generation') != evidence.get('generation')
                    or entry.get('evidence') != state or entry.get('active') is not True
                    or entry.get('release') in {'attempting', 'unknown', 'conflict'}
                    or type(since) not in (int, float) or not math.isfinite(since)
                    or not 0 <= since <= now):
                report['complete'] = False
                continue
            if now - since >= thresholds[name]:
                report['orphaned'] += 1
    except Exception:
        report['complete'] = False
    write_json_atomic(Path(root) / 'stranded-work/orphans.json', report)


def metrics(root, *, now):
    try:
        report = _read(Path(root) / 'stranded-work/orphans.json')
        stamp = report['checked_at']
        ok = (report['complete'] is True and type(stamp) in (int, float)
              and math.isfinite(stamp) and 0 <= now - stamp <= 900
              and type(report['orphaned']) is int and report['orphaned'] >= 0)
    except (OSError, ValueError, TypeError, KeyError):
        report, stamp, ok = {}, now, False
    if type(stamp) not in (int, float) or not math.isfinite(stamp) or stamp > now:
        stamp, ok = now, False
    lines = [f'shantytown_item_census_complete {int(ok)}',
             f'shantytown_item_census_timestamp_seconds {stamp}']
    if ok:
        lines.append(f'shantytown_orphaned_work{{kind="items"}} {report["orphaned"]}')
    return '\n'.join(lines) + '\n'
