#!/usr/bin/env python3
"""Real receipt coordinator with disposable file items and an unobserved send."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[3]
BASE = '7852a0dc84ce4c194cd6868d38064f65e409e9e9'


def probe(source):
    sys.path.insert(0, source)
    from shantytown.dispatch import Dispatcher, SendUnverified
    from shantytown.dispatch_binding import binding_for
    from shantytown.dispatch_receipts import ReceiptConflict
    from shantytown.files import FilesRegistry, FilesTracker
    from shantytown.protocols import SubmissionObserved
    from shantytown.tmux import NullPanes

    class Panes(NullPanes):
        def runtime_identity(self, pane):
            return 'fixture-process'

        def send(self, pane, text, **kw):
            super().send(pane, text, **kw)
            if not self._drops:
                return SubmissionObserved(pane, hashlib.sha256(text.encode()).hexdigest())

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        (root / 'crew').mkdir()
        (root / 'crew/worker.json').write_text(json.dumps(dict(pane='%5', harness='codex')))
        registry = FilesRegistry(root / 'crew')
        tracker = FilesTracker(root / 'items')
        tracker.update('work-1', title='Fixture work', status='open', priority=2)
        panes = Panes(screen='', created={'%5': 123})
        panes._drops = True
        binding = binding_for(root, tracker, registry, panes)
        dispatcher = Dispatcher(registry, tracker, panes, binding=binding)
        try:
            dispatcher.go('work-1', 'worker')
        except SendUnverified:
            pass
        old = binding.store.pending('work-1')
        try:
            dispatcher.go('work-1', 'worker')
        except ReceiptConflict:
            pass
        else:
            raise AssertionError('pending retry unexpectedly sent')
        item, sent = tracker.get('work-1'), len(panes.sent)
        try:
            result = binding.supersede(old['id'])
        except ReceiptConflict:
            result = dict(state='REFUSED')
        answer = dict(retirement=result['state'],
                      retirement_sends=len(panes.sent) - sent,
                      retirement_item_unchanged=tracker.get('work-1') == item,
                      old_execution_authorized=binding.reconcile(old['id'])['execution_authorized'])
        if result['state'] == 'superseded':
            panes._drops = False
            new = dispatcher.go('work-1', 'worker')
            answer['fresh_receipt'] = new.receipt_id != old['id']
            answer['fresh_execution_authorized'] = binding.reconcile(new.receipt_id)['execution_authorized']
        print(json.dumps(answer, sort_keys=True))


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--probe':
        probe(sys.argv[2])
        return
    print('Disposable file-backed items; simulated unobserved send. No live pane or tracker.', flush=True)
    print('Same input: prepare, fail to observe submission, retry once, explicitly retire.', flush=True)
    with tempfile.TemporaryDirectory() as folder:
        archive = subprocess.check_output(['git', 'archive', BASE, 'shantytown'], cwd=ROOT)
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            bundle.extractall(folder, filter='data')
        print('BASE ' + BASE, flush=True)
        before = json.loads(subprocess.check_output([sys.executable, __file__, '--probe', folder]))
        print(json.dumps(before, sort_keys=True), flush=True)
        print('CANDIDATE source checkout', flush=True)
        after = json.loads(subprocess.check_output([sys.executable, __file__, '--probe', str(ROOT)]))
        print(json.dumps(after, sort_keys=True), flush=True)
        assert before['retirement'] == 'REFUSED' and after['retirement'] == 'superseded'
        for result in (before, after):
            assert result['retirement_sends'] == 0 and result['retirement_item_unchanged']
            assert not result['old_execution_authorized']
        assert after['fresh_receipt'] and after['fresh_execution_authorized']
    print('PASS: explicit retirement enables a new receipt; it never sends, claims, or revives the old ID.')


if __name__ == '__main__':
    main()
