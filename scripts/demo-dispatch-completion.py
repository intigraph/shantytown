#!/usr/bin/env python3
"""Source-only demo with real receipt/file CAS and a synthetic pane adapter."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, sys.argv[1])
from shantytown.dispatch import Dispatcher, SendUnverified
from shantytown.dispatch_binding import binding_for
from shantytown.files import FilesRegistry, FilesTracker
from shantytown.protocols import SubmissionObserved
from shantytown.tmux import NullPanes, Tmux


class Pane(NullPanes):
    proof = False
    def runtime_identity(self, pane):
        return 'synthetic-original-process'
    def send(self, pane, text):
        super().send(pane, text)
        return None
    def observed_submission(self, pane, text, session, created, runtime, worker):
        if self.proof:
            return SubmissionObserved(pane, hashlib.sha256(text.encode()).hexdigest())


terminal = Tmux(socket='fixture-only')
terminal.cmdline = lambda _: 'claude --settings /fixture/worker.json'
print('Version-named Claude positively identified:', terminal._confirmed_claude('fixture-pane', '2.1.321'))
with tempfile.TemporaryDirectory(prefix='dispatch-demo-') as temp:
    root = Path(temp)
    (root / 'crew').mkdir()
    (root / 'crew/worker.json').write_text(json.dumps({'pane':'fixture-pane','harness':'claude'}))
    tracker, registry = FilesTracker(root / 'items'), FilesRegistry(root / 'crew')
    tracker.update('demo-1', title='Synthetic bounded work', status='open', priority=2)
    panes = Pane(screen='', created={'fixture-pane':123})
    binding = binding_for(root, tracker, registry, panes)
    dispatcher = Dispatcher(registry, tracker, panes, binding=binding)
    try:
        dispatcher.go('demo-1', 'worker', note='Original immutable qualifier')
    except SendUnverified:
        pass
    row = binding.store.pending('demo-1')
    print('Interrupted observation:', row['state'], 'authorized=', binding.reconcile(row['id'])['execution_authorized'])
    if not hasattr(dispatcher, 'complete'):
        print('Receipt-only completion: unavailable on this source')
    else:
        try:
            dispatcher.complete('demo-1', 'worker', receipt=row['id'])
            raise AssertionError('missing proof must refuse')
        except ValueError:
            print('Without native proof: fenced; no send or claim')
        panes.proof = True  # Synthetic adapter evidence; no live session involved.
        result = dispatcher.complete('demo-1', 'worker', receipt=row['id'])
        print('With exact retained proof:', result['state'], 'authorized=', result['execution_authorized'])
        dispatcher.complete('demo-1', 'worker', receipt=row['id'])
        assert len(panes.sent) == 1 and tracker.get('demo-1').revision == 2
        print('Repeated completion: one original body, one native CAS, no resend')
    print('Total bodies sent:', len(panes.sent), 'task revision:', tracker.get('demo-1').revision)
