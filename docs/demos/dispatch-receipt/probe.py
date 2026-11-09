"""Actual dispatch code; isolated file tracker and substituted terminal only."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile

for key in list(os.environ):
    if key.startswith(('SHANTY_', 'ST_')):
        os.environ.pop(key)

from shantytown.dispatch import Dispatcher, SendUnverified
from shantytown.feed_audit import FeedAudit
from shantytown.files import FilesRegistry, FilesTracker
from shantytown.protocols import SubmissionObserved
from shantytown.tmux import NullPanes

parser = argparse.ArgumentParser()
parser.add_argument('--expect', choices=['base', 'candidate'], required=True)
args = parser.parse_args()
qualified = importlib.util.find_spec('shantytown.dispatch_binding') is not None
if qualified:
    from shantytown.dispatch_binding import binding_for


class Terminal(NullPanes):
    def __init__(self, mode):
        super().__init__(screen='Earlier mention of fixture-1' if mode == 'stale' else '',
                         drops=mode != 'observed', created={'%5': 123})
        self.mode = mode

    def runtime_identity(self, pane):
        return "isolated-fixture-process-1"

    def send(self, pane, text, **kw):
        super().send(pane, text, **kw)
        if self.mode == 'observed':
            return SubmissionObserved(pane, hashlib.sha256(text.encode()).hexdigest())


results = []
with tempfile.TemporaryDirectory(prefix='dispatch-receipt-demo-') as directory:
    for mode in ['stale', 'unobserved', 'observed']:
        root = Path(directory) / mode
        (root / 'crew').mkdir(parents=True)
        (root / 'crew/worker.json').write_text(json.dumps(dict(role='worker', pane='%5', harness='codex')))
        tracker = FilesTracker(root / 'items')
        tracker.update('fixture-1', title='A bounded example', status='open')
        registry, terminal = FilesRegistry(root / 'crew'), Terminal(mode)
        kw = dict(audit=FeedAudit(root))
        if qualified:
            kw['binding'] = binding_for(root, tracker, registry, terminal)
        dispatcher = Dispatcher(registry, tracker, terminal, **kw)
        try:
            plan = dispatcher.go('fixture-1', 'worker', note='retain this scope')
            outcome = 'accepted'
        except SendUnverified:
            plan, outcome = None, 'unverified'
        assigned = tracker.get('fixture-1').assignee == 'worker'
        pending = len(list((root / 'dispatch-receipts').glob('*.json')))
        result = dict(input=mode, outcome=outcome, assigned=assigned, sends=len(terminal.sent),
                      receipt_files=pending)
        if mode == 'observed':
            replay = dispatcher.go('fixture-1', 'worker', note='retain this scope')
            result['sends_after_replay'] = len(terminal.sent)
            if qualified:
                binding = kw['binding']
                before = {str(p): (p.read_bytes(), p.stat().st_mtime_ns)
                          for p in root.rglob('*') if p.is_file()}
                status = binding.reconcile(plan.receipt_id)
                after = {str(p): (p.read_bytes(), p.stat().st_mtime_ns)
                         for p in root.rglob('*') if p.is_file()}
                result.update(same_receipt=replay.receipt_id == plan.receipt_id,
                              execution_authorized=status['execution_authorized'],
                              reconciliation_read_only=before == after)
        results.append(result)
        print(json.dumps(result, sort_keys=True))

if args.expect == 'base':
    assert not qualified and results[0]['assigned'] and not results[1]['assigned']
    assert results[2]['sends_after_replay'] == 2
else:
    assert qualified and not results[0]['assigned'] and not results[1]['assigned']
    assert results[0]['receipt_files'] == results[1]['receipt_files'] == 1
    assert results[2]['sends_after_replay'] == 1 and results[2]['same_receipt']
    assert results[2]['execution_authorized'] and results[2]['reconciliation_read_only']
print('Expected measurements verified; source fixture only, no live pane or model call.')
