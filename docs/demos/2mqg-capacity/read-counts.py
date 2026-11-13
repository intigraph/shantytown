#!/usr/bin/env python3
"""Guard-only library fixture: transport and final writes are mocked."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def observe(ref):
    source = subprocess.check_output(
        ['git', 'show', f'{ref}:shantytown/plate_capacity.py'], cwd=ROOT, text=True)
    module = type(sys)(f'shantytown._capacity_demo_{ref[:12]}')
    module.__package__ = 'shantytown'
    exec(compile(source, '<capacity-source-fixture>', 'exec'), module.__dict__)
    counts = dict(sdk_show_reads=0, field_reads=0, writes=0)
    row = dict(id='fixture', title='Work', status='open', assignee='worker',
               labels=[], defer_until=None, blocker_kind=None)

    class Tracker:
        def get(self, identifier):
            counts['sdk_show_reads'] += 1
            return SimpleNamespace(**row)

        def capacity_read(self, identifier):
            counts['field_reads'] += 1
            return SimpleNamespace(**row)

        def create(self, *args, **fields):
            raise AssertionError('the fixture never creates work')

        def update(self, identifier, **fields):
            counts['writes'] += 1
            row.update(fields)

    tracker = module.guard_producers(Tracker(), lambda *args: None)
    tracker.update('fixture', defer_until='2999-12-01T00:00:00Z')
    tracker.update('fixture', status='deferred')
    assert counts['writes'] == 2
    return dict(ref=ref, **counts)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    parser.add_argument('--head', required=True)
    args = parser.parse_args()
    print('SOURCE FIXTURE: capacity guard calls only; no real SDK, graph or latency measurement')
    with tempfile.TemporaryDirectory(prefix='capacity-fields-demo-') as sandbox_home:
        with patch.dict(os.environ, {'HOME': sandbox_home}):
            for ref in (args.base, args.head):
                print(json.dumps(observe(ref), sort_keys=True))
