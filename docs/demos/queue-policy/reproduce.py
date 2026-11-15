"""Synthetic in-memory tracker only; never opens a pane or production store."""
import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path, required=True)
parser.add_argument('--full', action='store_true')
parser.add_argument('--off', action='store_true')
args = parser.parse_args()
sys.path.insert(0, str(args.source.resolve()))
for name in list(os.environ):
    if name.startswith(('SHANTY_', 'ST_')) or name == 'QUIPU_SERVER':
        del os.environ[name]
os.environ['SHANTY_QUEUE_POLICY'] = 'off' if args.off else 'enforce'
from shantytown import cli
from shantytown.protocols import WorkItem

class Tracker:
    def __init__(self):
        self.value = None
        self.writes = []

    def queue_rows(self):
        if args.full:
            return [dict(id=f'test-{n}', lane='next', status='open', rank=str(n)) for n in range(40)]
        return [vars(self.value)] if self.value and getattr(self.value, 'lane', None) else []

    def create(self, title, **fields):
        self.writes.append('create')
        self.value = WorkItem('test-request', title=title, revision=1)
        return self.value

    def get(self, ident):
        assert ident == 'test-request'
        return self.value

    def update(self, ident, **fields):
        assert ident == 'test-request' and fields['if_revision'] == self.value.revision
        self.writes.append('queue CAS')
        self.value = replace(self.value, lane=fields['lane'], rank=fields['rank'], revision=2)

tracker = Tracker()
cli._tracker = lambda _: tracker
with tempfile.TemporaryDirectory() as root:
    code = cli.main(['--root', root, 'task', 'review this new request'])
print(json.dumps({'exit': code, 'writes': tracker.writes,
                  'lane': getattr(tracker.value, 'lane', None),
                  'rank': getattr(tracker.value, 'rank', None)}, sort_keys=True))
