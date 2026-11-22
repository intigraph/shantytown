"""Pure watch evidence evaluation; no collector, launcher, approval or Actions.

Source adapters share WatchSpec validation. An admitted controller must verify
reader provenance and the frozen deployment receipt before supplying evidence.
A Result is not a signed verdict or permission to compensate/close an item.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Mapping


class WatchRefused(ValueError):
    pass


def _finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


@dataclass(frozen=True)
class WatchSpec:
    run_id: str
    source_digest: str
    deployment_receipt: str
    identity: str
    start: int
    window_seconds: int
    sample_seconds: int
    maximum: tuple[tuple[str, float], ...]

    @classmethod
    def validate(cls, value: Mapping) -> WatchSpec:
        fields = {'version', 'run_id', 'source_digest', 'deployment_receipt',
                  'identity', 'start', 'window_seconds', 'sample_seconds', 'maximum'}
        if not isinstance(value, dict) or set(value) != fields or type(value['version']) is not int or value['version'] != 1:
            raise WatchRefused('one exact versioned watch specification required')
        for key in ('run_id', 'deployment_receipt', 'identity'):
            if not isinstance(value[key], str) or not 1 <= len(value[key]) <= 256:
                raise WatchRefused('missing frozen watch binding: ' + key)
        if not isinstance(value['source_digest'], str) or not re.fullmatch('[0-9a-f]{64}', value['source_digest']):
            raise WatchRefused('exact selected source digest required')
        for key in ('start', 'window_seconds', 'sample_seconds'):
            if type(value[key]) is not int or value[key] <= 0:
                raise WatchRefused('positive integer timing required')
        if not value['sample_seconds'] <= value['window_seconds'] <= 86400:
            raise WatchRefused('watch timing outside program ceiling')
        if math.ceil(value['window_seconds'] / value['sample_seconds']) + 1 > 4097:
            raise WatchRefused('sample count exceeds program ceiling')
        limits = value['maximum']
        if not isinstance(limits, dict) or not 1 <= len(limits) <= 32:
            raise WatchRefused('bounded nonempty metric limits required')
        if any(not isinstance(k, str) or not re.fullmatch('[a-z][a-z0-9_]{0,63}', k)
               or not _finite(v) or v < 0 for k, v in limits.items()):
            raise WatchRefused('finite nonnegative named metric limits required')
        return cls(**{k: value[k] for k in fields - {'version', 'maximum'}},
                   maximum=tuple(sorted(limits.items())))

    @property
    def end(self):
        return self.start + self.window_seconds

    def grid(self):
        # Always include the original end, even when cadence does not divide it.
        return (*range(self.start, self.end, self.sample_seconds), self.end)


@dataclass(frozen=True)
class Observation:
    at: int
    identity: str
    metrics: Mapping[str, float]


@dataclass(frozen=True)
class WatchResult:
    safety: str
    activation: str
    improvement: str
    reasons: tuple[str, ...]
    compensation: str = 'NOT_EXECUTED'


def next_sample_at(spec: WatchSpec, last: int | None) -> int | None:
    """Resume the frozen grid; do not restart the clock after a collector crash."""
    if last is None:
        return spec.start
    if type(last) is not int or last not in spec.grid():
        raise WatchRefused('last sample is not on the frozen grid')
    return min(last + spec.sample_seconds, spec.end) if last < spec.end else None


def evaluate_watch(spec: WatchSpec, samples: list[Observation], *, now: float,
                   activation: str, comparison: tuple[float, float] | None = None,
                   comparable: bool = False) -> WatchResult:
    """Evaluate already qualified evidence, without authentication or effects.

    `activation` comes from the native activation probe, never a config flag.
    comparison is (before, after) for a lower-is-better measure; its cohort
    admission belongs to the caller. Missing or flat evidence is not a gain.
    """
    if activation not in ('ACTIVE', 'INACTIVE', 'UNKNOWN'):
        raise WatchRefused('native activation verdict required')
    reasons = []
    if not _finite(now) or now < spec.start:
        return WatchResult('UNKNOWN', 'UNKNOWN', 'NOT_EVALUATED', ('clock outside original window',))
    if len(samples) > len(spec.grid()):
        return WatchResult('UNKNOWN', activation, 'NOT_EVALUATED', ('excess or duplicate samples',))
    if any(not isinstance(row, Observation) for row in samples):
        raise WatchRefused('typed observations required')
    if any(row.identity != spec.identity for row in samples):
        return WatchResult('SUPERSEDED', 'UNKNOWN', 'NOT_EVALUATED', ('deployment identity changed',))
    points = [row.at for row in samples]
    if any(type(t) is not int for t in points) or points != list(spec.grid()[:len(points)]):
        return WatchResult('UNKNOWN', activation, 'NOT_EVALUATED', ('missing, reordered or duplicate samples',))
    if any(t > now for t in points):
        return WatchResult('UNKNOWN', activation, 'NOT_EVALUATED', ('future sample',))
    limits = dict(spec.maximum)
    for row in samples:
        if not isinstance(row.metrics, Mapping):
            reasons.append('metric coverage incomplete')
            continue
        if set(row.metrics) != set(limits):
            reasons.append('metric coverage incomplete')
        for key in sorted(set(row.metrics) & set(limits)):
            value = row.metrics[key]
            if not _finite(value) or value < 0:
                reasons.append('invalid metric: ' + key)
            elif value > limits[key]:
                reasons.append('bound exceeded: ' + key)
    breach = any(r.startswith('bound exceeded:') for r in reasons)
    if breach:
        safety = 'BREACH'  # A real bound breach survives another missing probe.
    elif reasons:
        safety = 'UNKNOWN'
    elif len(samples) == len(spec.grid()) and now >= spec.end:
        safety = 'PASS'
    elif now >= spec.end:
        safety = 'UNKNOWN'
        reasons.append('original window ended with incomplete coverage')
    else:
        safety = 'OBSERVING'
    improvement = 'NOT_EVALUATED'
    if safety == 'PASS' and activation == 'ACTIVE':
        improvement = 'UNKNOWN'
        if (comparable is True and isinstance(comparison, tuple) and len(comparison) == 2
                and all(_finite(x) and x > 0 for x in comparison)):
            improvement = 'IMPROVED' if comparison[1] < comparison[0] else 'NO_IMPROVEMENT'
    return WatchResult(safety, activation, improvement, tuple(dict.fromkeys(reasons)))
