"""Durable per-host count of plate-capacity admission outcomes (aegis-jve).

Every admission read records ONE outcome line:

- ``live``: the exact owner read succeeded;
- ``snapshot``: quipu signalled busy and admission counted from a fresh
  same-store snapshot instead (``owner_snapshot``);
- ``unknown_busy``: quipu signalled busy and no fresh snapshot existed, so
  admission refused with "plate size UNKNOWN";
- ``unknown_other``: any other failure refused with "plate size UNKNOWN".

The file is JSON lines under ``$XDG_STATE_HOME/shantytown`` (mode 0600), and
rotates once past ``MAX_BYTES`` into a single ``.1`` generation.
``SHANTYTOWN_PLATE_OUTCOMES`` names another file (tests set it so child
processes never write the developer's state). Recording is
best effort: a storage failure never changes the admission decision.

Count with ``python -m shantytown.plate_outcomes [--since ISO8601]``.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import sys
import time

OUTCOMES = ('live', 'snapshot', 'unknown_busy', 'unknown_other')
MAX_BYTES = 4 * 1024 * 1024
FILENAME = 'plate-admission-outcomes.jsonl'


def path() -> Path:
    override = os.environ.get('SHANTYTOWN_PLATE_OUTCOMES')
    if override:
        return Path(override)
    base = Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local' / 'state')
    return base / 'shantytown' / FILENAME


def record(outcome: str, owner: str, *, at: float | None = None) -> None:
    if outcome not in OUTCOMES:
        raise ValueError(f'unknown plate admission outcome {outcome!r}')
    try:
        target = path()
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            if target.stat().st_size > MAX_BYTES:
                os.replace(target, target.with_name(FILENAME + '.1'))
        except FileNotFoundError:
            pass
        line = json.dumps({'at': time.time() if at is None else at, 'host': socket.gethostname(),
                           'owner': owner, 'outcome': outcome}, sort_keys=True) + '\n'
        fd = os.open(target, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'a') as stream:
            stream.write(line)
    except (OSError, ValueError, TypeError):
        return


def counts(since: float = 0.0, *, files: list[Path] | None = None) -> Counter:
    """Outcome counts at or after ``since`` across the current and rotated files."""
    found: Counter = Counter()
    for source in files if files is not None else [path().with_name(FILENAME + '.1'), path()]:
        try:
            lines = source.read_text().splitlines()
        except FileNotFoundError:
            continue
        for line in lines:
            try:
                entry = json.loads(line)
            except ValueError:
                found['unreadable'] += 1
                continue
            if (isinstance(entry, dict) and entry.get('outcome') in OUTCOMES
                    and isinstance(entry.get('at'), (int, float)) and entry['at'] >= since):
                found[entry['outcome']] += 1
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--since', help='ISO 8601 instant with a timezone; default: everything retained')
    args = parser.parse_args(argv)
    since = 0.0
    if args.since:
        instant = datetime.fromisoformat(args.since.replace('Z', '+00:00'))
        if instant.tzinfo is None:
            parser.error('--since needs a timezone')
        since = instant.astimezone(timezone.utc).timestamp()
    found = counts(since)
    print(json.dumps({'file': str(path()), 'since': args.since,
                      **{name: found.get(name, 0) for name in OUTCOMES},
                      'unreadable': found.get('unreadable', 0)}, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
