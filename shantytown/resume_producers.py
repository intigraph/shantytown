"""Read producer-owned readiness; never run item-supplied queries or commands.

Recurring closure remains the alarm processor's responsibility. These events
only release a waiter for reassessment, not acceptance or policy promotion.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from .resume_events import Verdict, read_producer_file, _unique


@dataclass(frozen=True)
class CountObservation:
    """A reviewed producer answers for one exact corpus/window identity.

    The reader owns deduplication, completeness, freshness and any required
    subset coverage. Count is never inferred from missing or partial evidence.
    """
    candidate_ids: tuple[str, ...]
    identity: str
    observed_at: datetime
    complete: bool
    required_coverage: bool


@dataclass(frozen=True)
class Counter:
    item: str
    identity: str
    reader: Callable[[], CountObservation]
    freshness: timedelta
    require_coverage: bool = True


# A source-reviewed reader must be installed before a counter is writable.
# Policy49's retained advice logs are not a complete producer-owned corpus.
COUNTERS: dict[str, Counter] = {}


def validate(kind: str, arg: str):
    if kind == 'recurring-quiet':
        if not re.fullmatch(r'[0-9a-f]{24}', arg):
            raise ValueError('recurring-quiet requires the processor class hash')
        return arg
    if kind == 'evidence-count':
        match = re.fullmatch(r'([a-z][a-z0-9-]{0,63})>=([1-9][0-9]{0,6})', arg)
        if not match or match[1] not in COUNTERS:
            raise ValueError('evidence-count requires a registered producer ID>=N')
        return match[1], int(match[2])
    raise ValueError('unsupported producer event')


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError('invalid producer timestamp')
    return value


def _deferred_at(row, now):
    from .deferral_notes import PROVENANCE_PREFIX, parse_provenance
    from .deferrals import parse_stamp
    lines = [line for line in str(row.get('notes') or '').splitlines()
             if line.lstrip().startswith(PROVENANCE_PREFIX.rstrip(': '))]
    value = parse_provenance(lines[0]) if len(lines) == 1 else None
    start = parse_stamp(value['set_at']) if value else None
    if start is None or start > now:
        raise ValueError('missing or ambiguous deferral boundary')
    return start.timestamp()


def _recurring(identifier, row, now):
    path = Path.home() / '.local/state/recurring-alarms/state.json'
    raw = read_producer_file(path, 4 * 1024 * 1024)
    data = json.loads(raw, object_pairs_hook=_unique)
    if type(data['version']) is not int or data['version'] != 1:
        raise ValueError('unsupported recurring producer version')
    stamp = now.timestamp()
    census = _number(data['last_census'])
    if not 0 <= stamp - census <= 600:
        raise ValueError('recurring census unavailable or stale')
    source = data['classes'][identifier]
    if source['bead'] != row['id'] or type(source['active']) is not bool:
        raise ValueError('recurring class/item identity mismatch')
    fired = _number(source['last_fired'])
    if fired > census:
        raise ValueError('recurring firing is newer than census')
    start = _deferred_at(row, now)
    if fired > start:
        return Verdict('MET', 'producer reports refire after deferral')
    if source['active']:
        return Verdict('NOT_MET', 'class still active; no new firing after deferral')
    quiet = _number(source['quiet_since'])
    if not fired <= quiet <= census:
        raise ValueError('invalid producer quiet interval')
    # Use the last authoritative observation, not wall time since a dead poller.
    ready = census - quiet >= timedelta(days=14).total_seconds()
    return Verdict('MET' if ready else 'NOT_MET',
                   'producer quiet interval', hashlib.sha256(raw).hexdigest())


def evaluate(kind: str, arg: str, row: dict, now: datetime) -> Verdict:
    try:
        if now.tzinfo is None:
            raise ValueError('evaluation time must be timezone aware')
        parsed = validate(kind, arg)
        if kind == 'recurring-quiet':
            return _recurring(parsed, row, now)
        identifier, threshold = parsed
        binding = COUNTERS[identifier]
        if binding.item != row['id'] or not binding.identity:
            raise ValueError('counter is not registered for this item/identity')
        observation = binding.reader()
        if (not isinstance(observation, CountObservation)
                or observation.identity != binding.identity
                or observation.complete is not True
                or not isinstance(observation.candidate_ids, tuple)
                or len(observation.candidate_ids) > 10000
                or any(not isinstance(value, str) or not value or len(value) > 256
                       for value in observation.candidate_ids)
                or len(set(observation.candidate_ids)) != len(observation.candidate_ids)
                or type(observation.required_coverage) is not bool
                or observation.observed_at.tzinfo is None
                or not timedelta(0) <= now-observation.observed_at <= binding.freshness):
            raise ValueError('counter observation incomplete, stale or identity mismatch')
        ready = (len(observation.candidate_ids) >= threshold
                 and (not binding.require_coverage or observation.required_coverage))
        return Verdict('MET' if ready else 'NOT_MET',
                       'registered producer count')
    except Exception as exc:
        # Reader exceptions cannot turn into zero, acceptance or a date release.
        return Verdict('UNKNOWN', f'producer evidence unavailable: {type(exc).__name__}')
