"""Offline watch adapter: no collectors, credentials, Actions or job launches.

# arming: agent-invoked replay of bounded local fixture files.
Both JSON and TOML feed the same WatchSpec validator. These unsigned local
results are evidence evaluation, never an activation or compensation receipt.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
import tomllib

from .watch_program import Observation, WatchRefused, WatchSpec, evaluate_watch, next_sample_at

MAX_BYTES = 4 * 1024 * 1024


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise WatchRefused('duplicate JSON key: ' + key)
        result[key] = value
    return result


def _json(raw):
    def invalid(_):
        raise WatchRefused('non-finite JSON number')
    return json.loads(raw, object_pairs_hook=_unique, parse_constant=invalid)


def _read(path: Path):
    # Bound the read itself, including FIFOs/large inputs; only regular files.
    import os
    import stat
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise WatchRefused('regular local fixture file required')
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise WatchRefused('fixture exceeds byte ceiling')
    return raw.decode('utf-8')


def load_spec(path: Path) -> WatchSpec:
    raw = _read(path)
    if path.suffix == '.toml':
        value = tomllib.loads(raw)
    elif path.suffix == '.json':
        value = _json(raw)
    else:
        raise WatchRefused('explicit .json or .toml watch source required')
    return WatchSpec.validate(value)


def replay(spec: WatchSpec, value: dict) -> dict:
    fields = {'version', 'run_id', 'source_digest', 'deployment_receipt',
              'now', 'activation', 'samples'}
    if not isinstance(value, dict) or set(value) != fields or type(value['version']) is not int or value['version'] != 1:
        raise WatchRefused('exact versioned replay envelope required')
    for key in ('run_id', 'source_digest', 'deployment_receipt'):
        if value[key] != getattr(spec, key):
            raise WatchRefused('replay binding differs: ' + key)
    rows = value['samples']
    if not isinstance(rows, list) or len(rows) > len(spec.grid()):
        raise WatchRefused('bounded observation list required')
    observations = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'at', 'identity', 'metrics'}:
            raise WatchRefused('exact observation fields required')
        observations.append(Observation(**row))
    result = evaluate_watch(spec, observations, now=value['now'], activation=value['activation'])
    # A broken prefix has no safe resume cursor. Never silently skip a gap.
    points = [row.at for row in observations]
    valid_prefix = all(type(t) is int for t in points) and points == list(spec.grid()[:len(points)])
    next_at = next_sample_at(spec, points[-1] if points else None) if valid_prefix else None
    return {'schema': 'shantytown.watch-replay/v1', 'mode': 'OFFLINE_UNAUTHENTICATED',
            'run_id': spec.run_id, 'source_digest': spec.source_digest,
            'deployment_receipt': spec.deployment_receipt,
            'result': asdict(result), 'next_sample_at': next_at,
            'actions_executed': [], 'jobs_launched': []}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = replay(load_spec(args.spec), _json(_read(args.evidence)))
    except (WatchRefused, ValueError, OSError, TypeError, OverflowError) as error:
        print(json.dumps({'schema': 'shantytown.watch-replay/v1', 'refused': str(error)}))
        return 2
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result['result']['safety'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
