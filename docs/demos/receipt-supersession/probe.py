"""Isolated file tracker and terminal fixture; no production send or store."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[3])
a = parser.parse_args()
sys.path.insert(0, str(a.source.resolve()))
from shantytown.dispatch import Dispatcher
from shantytown.dispatch_binding import binding_for
from shantytown.dispatch_receipts import ReceiptConflict
from shantytown.files import FilesRegistry, FilesTracker
from shantytown.protocols import SubmissionObserved
from shantytown.tmux import NullPanes


class Terminal(NullPanes):
    def runtime_identity(self, pane):
        return 'isolated-process'

    def send(self, pane, text, **kw):
        super().send(pane, text, **kw)
        return SubmissionObserved(pane, hashlib.sha256(text.encode()).hexdigest())


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    (root / 'crew').mkdir()
    (root / 'crew/worker.json').write_text(json.dumps(dict(pane='%5', harness='codex')))
    tracker = FilesTracker(root / 'items')
    tracker.update('work-1', title='isolated work', status='open', priority=2)
    registry = FilesRegistry(root / 'crew')
    terminal = Terminal(created={'%5': 123}, screen='')
    binding = binding_for(root, tracker, registry, terminal)
    dispatcher = Dispatcher(registry, tracker, terminal, binding=binding)
    claim = binding.assignments.claim

    def interrupted(row, updates):
        claim(row, updates)
        raise KeyboardInterrupt()

    binding.assignments.claim = interrupted
    try:
        dispatcher.go('work-1', 'worker')
    except KeyboardInterrupt:
        pass
    binding.assignments.claim = claim
    old = binding.store.pending('work-1')
    tracker.update('work-1', status='open', assignee='')
    print('Interrupted claim, followed by a newer native release.')
    try:
        dispatcher.go('work-1', 'worker')
    except ReceiptConflict:
        print('Ordinary redispatch: refused; no second submission.')
    else:
        raise AssertionError('ordinary redispatch must remain fenced')
    if not hasattr(binding, 'supersede'):
        print('Explicit supersession: unavailable on this source.')
        print('Submissions:', len(terminal.sent), '; fresh authorization: unavailable')
    else:
        result = binding.supersede(old['id'])
        print('Explicit supersession:', result['state'], '; authorized:', result['execution_authorized'])
        new = dispatcher.go('work-1', 'worker')
        print('Fresh receipt authorized:', binding.reconcile(new.receipt_id)['execution_authorized'])
        print('Old receipt authorized:', binding.reconcile(old['id'])['execution_authorized'])
        print('Submissions:', len(terminal.sent), '(original + fresh; no replay)')
