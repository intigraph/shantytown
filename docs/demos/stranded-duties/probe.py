"""Same synthetic stopped owner and declared inventory on base and candidate.

No real board, process, credential, pushgateway or crew root is used.
Run this file with --source pointing at the checkout to demonstrate.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path, required=True)
args = parser.parse_args()
sys.path.insert(0, str(args.source.resolve()))
# Preserve the fixture's explicit isolation even from an inherited live shell.
for key in list(os.environ):
    if key.startswith(('SHANTY_', 'ST_')):
        os.environ.pop(key)
os.environ['SHANTY_STRANDED_WORK'] = 'release'

from shantytown.answer import Answer
from shantytown.files import write_json_atomic
from shantytown.inbox import FilesInbox
from shantytown.protocols import Agent
from shantytown.stopped import FilesStops
from shantytown import deployment, stranded_adapter

deployment.local_host = lambda _: 'fixture-host'
with tempfile.TemporaryDirectory(prefix='duty-demo-') as directory:
    root = Path(directory)
    cards = {name: Agent(name, role, pane=name, host='fixture-host')
             for name, role in [('worker', 'worker'), ('lead', 'lead'), ('admin', 'administrator')]}
    registry = SimpleNamespace(all=lambda: Answer.complete_read(list(cards.values()), how='fixture'),
                               get=lambda name: cards[name])
    states = dict(worker='down', lead='live', admin='live')
    panes = SimpleNamespace(owner_state=lambda name: states[name])
    ask = dict(id='decision', title='ASK operator: retained', assignee='worker',
               status='open', priority=0, labels=['needs-stiwi'])
    repairs = {}
    def create(payload, *, target, key):
        repairs.setdefault(key, SimpleNamespace(id='repair-' + str(len(repairs))))
        return repairs[key]
    def unexpected_release(*_args, **_kwargs):
        raise AssertionError('ASK was released')
    tracker = SimpleNamespace(stranded_rows=lambda _: [copy.deepcopy(ask)],
        stranded_read=lambda _: copy.deepcopy(ask), release_stranded=unexpected_release,
        create_duty_issue=create)
    inbox = FilesInbox(root / 'inbox')
    rows = [dict(id=ident, holder='worker', kind=kind, binding=binding,
                 priority=0, source='fixture:binding', candidates=['lead'], authors=[])
            for ident, kind, binding in [('queue', 'merge-queue', 'registry'),
                                         ('peer', 'review-reservation', 'external')]]
    path = root / 'duties/registry.json'
    path.parent.mkdir()
    write_json_atomic(path, dict(schema='shantytown.duties/1', revision=1,
        coverage=['merge-queue', 'reviewer', 'scheduled-job', 'alert-keeper', 'review-reservation', 'haul'],
        entries=rows))
    FilesStops(root / 'stopped').record('worker', 0)
    for stamp in (1800, 1801):
        stranded_adapter.sweep(root, registry, tracker, panes, inbox, now=stamp)
    current = json.loads(path.read_text())
    print('queue holder:', next(row['holder'] for row in current['entries'] if row['id'] == 'queue'))
    print('external reservation holder:', next(row['holder'] for row in current['entries'] if row['id'] == 'peer'))
    print('repair records after two passes:', len(repairs))
    print('administrator pages:', len(inbox.unread('admin')))
    print('ASK owner:', ask['assignee'])
    if (args.source / 'shantytown/duties.py').exists():
        from shantytown.duties import summary
        from shantytown.duty_adapter import stop_guard
        print(summary(root, now=1801))
        stop = SimpleNamespace(root=root, agent='worker', dry_run=False, repool_work=False)
        try:
            stop_guard(stop, lambda: (_ for _ in ()).throw(AssertionError('pane stopped')),
                       registry=registry, panes=panes, inbox=inbox, tracker=tracker, host='fixture-host')
        except ValueError:
            print('stop without explicit disposition: REFUSED before pane stop')
    else:
        print('duty summary/stop guard: unavailable in base')
