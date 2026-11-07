"""Read retained advisory outcomes off the create path; never run an advisory.

# arming: scheduled managed host exporter; no model or tracker operations.
"""
from collections import Counter
from datetime import datetime
import json
import math
from pathlib import Path
import time

WINDOW = 7 * 24 * 3600
MAX_BYTES = 16 * 1024 * 1024


def reason_code(reason):
    """Bounded labels; raw errors, titles and credential-shaped text never export."""
    value = str(reason or '').lower()
    if value.startswith('configure '): return 'missing_configuration'
    if value.startswith('search, store or jev'): return 'legacy_unavailable'
    if value.startswith('search unavailable'): return 'search_unavailable'
    if value.startswith('candidate store'): return 'store_unavailable'
    if value.startswith('jev unavailable'): return 'jev_unavailable'
    if value.startswith('complex shell'): return 'complex_shell'
    if value.startswith('unsupported '): return 'unsupported_option'
    if 'time budget' in value: return 'deadline'
    if value.startswith('worker unavailable'): return 'worker_unavailable'
    return 'other'


def coverage_report(path, *, now=None):
    now = time.time() if now is None else now
    result = dict(schema='st.create-advisory-coverage/1', as_of=now,
                  window_seconds=WINDOW, log_read_ok=False)
    try:
        source = Path(path)
        if source.stat().st_size > MAX_BYTES:
            raise ValueError('oversized log')
        content = source.read_bytes()
        if len(content) > MAX_BYTES:
            raise ValueError('oversized log')
        counts, skips, seen = Counter(), Counter(), set()
        last = None
        for line in content.splitlines():
            if not line.strip(): continue
            row = json.loads(line)
            event = row['event_id']
            if not isinstance(event, str) or not event or event in seen:
                raise ValueError('ambiguous event identity')
            seen.add(event)
            at = datetime.fromisoformat(row['at'].replace('Z', '+00:00'))
            if at.tzinfo is None or row['outcome'] not in {'fired', 'no-match', 'skipped'}:
                raise ValueError('invalid event')
            stamp = at.timestamp()
            if not math.isfinite(stamp) or stamp > now + 60:
                raise ValueError('invalid event clock')
            last = stamp if last is None else max(last, stamp)
            if now - WINDOW <= stamp <= now:
                counts[row['outcome']] += 1
                if row['outcome'] == 'skipped': skips[reason_code(row.get('reason'))] += 1
        total = sum(counts.values())
        result.update(log_read_ok=True, events=total, skipped=counts['skipped'],
                      evaluated=counts['fired'] + counts['no-match'], warned=counts['fired'],
                      no_match=counts['no-match'], skip_reasons=dict(skips),
                      skip_ratio=counts['skipped'] / total if total else None,
                      last_event=last)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        # Never turn an unreadable, partial or invalid population into zero skips.
        result['error'] = 'retained log unavailable or invalid'
    return result
