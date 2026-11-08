"""Actual Tmux wrapper/coordinator composition; isolated tracker and fake _send."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--source', required=True)
parser.add_argument('--expect', choices=['before', 'after'], required=True)
args = parser.parse_args()
source = Path(args.source).resolve()
sys.path[:0] = [str(source), str(source / 'tests')]
from test_dispatch_binding import world
from shantytown.dispatch import SendUnverified
from shantytown.dispatch_receipts import ReceiptConflict
from shantytown.protocols import SubmissionObserved
from shantytown.tmux import Tmux

for observed in [False, True]:
    with tempfile.TemporaryDirectory() as folder:
        root, dispatcher, binding, tracker, panes = world.__wrapped__(Path(folder))
        transport = Tmux(root=root)
        transport.runtime_identity = panes.runtime_identity
        calls = []
        def send(pane, text, *, custody=None):
            calls.append(text)
            custody.begin(text, 123)
            return SubmissionObserved(pane, hashlib.sha256(text.encode()).hexdigest()) if observed else None
        transport._send = send
        def interrupted(pane, text):
            transport.send(pane, text)
            return None  # coordinator loses transport's return
        panes.send = interrupted
        try:
            dispatcher.go('work-1', 'worker')
        except SendUnverified:
            pass
        else:
            raise AssertionError('interrupted observation must remain pending')
        row = binding.store.pending('work-1')
        try:
            dispatcher.go('work-1', 'worker')
        except ReceiptConflict:
            pass
        authorized = binding.reconcile(row['id'])['execution_authorized']
        print(json.dumps(dict(submission_observed=observed, sends=len(calls),
            assignee=tracker.get('work-1').assignee, execution_authorized=authorized), sort_keys=True))
        assert len(calls) == 1
        assert authorized == (observed or args.expect == 'before')
        assert (tracker.get('work-1').assignee == 'worker') == authorized
