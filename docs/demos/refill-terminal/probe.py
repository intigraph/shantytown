"""Isolated library demonstration; no real tracker, process or deployment calls."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from test_refill_reconcile import packet, put
from shantytown import refill_reconcile as before
from shantytown import refill_terminal_reconcile as after
from shantytown.answer import Answer


class NativeFixture:
    owner = None

    def show(self, item):
        return Answer.complete_read(dict(id=item, status='open', assignee=self.owner,
                                        revision=7), how='isolated tracker fixture')


with tempfile.TemporaryDirectory() as folder:
    root, old_request, state, custody, _ = packet.__wrapped__(Path(folder))
    custody.update(state='orphaned', pointer='fixture-pointer', pointer_state='recorded')
    path = root / 'delivery' / (custody['id'] + '.json')
    put(path, custody)
    original = path.read_bytes()
    print('Fixture: ended composer, recorded pointer, unassigned native work.')
    try:
        before.reconcile(root, old_request, now=1100)
        raise AssertionError('base should refuse terminal custody')
    except ValueError as exc:
        print('BEFORE existing delivery proof path:', str(exc))
    state['pending']['worker']['lane'] = 'next'
    put(root / 'refill/state.json', state)
    request = dict(version=1, worker='worker', item='work-1',
                   pending=state['pending']['worker'], custody=custody['id'],
                   custody_sha256=hashlib.sha256(original).hexdigest())
    tracker = NativeFixture()
    tracker.owner = 'worker'
    try:
        after.reconcile(root, request, apply=True, tracker=tracker)
        raise AssertionError('live held work must refuse')
    except ValueError as exc:
        print('NEGATIVE live owner holds item:', str(exc))
    tracker.owner = None
    result = after.reconcile(root, request, apply=True, tracker=tracker)
    print('AFTER unassigned native item:', json.dumps({k: result[k] for k in
          ('state', 'delivery', 'custody_state')}, sort_keys=True))
    current = before.read(root / 'refill/state.json')
    assert 'worker' not in current['pending'] and 'other' in current['pending']
    assert path.read_bytes() == original
    audit = before.audit_rows(root / 'refill/terminal-reconciliations.jsonl')
    assert audit[0]['original_pending']['lane'] == 'next'
    print('Verified: only exact reservation released; lane audited; custody bytes unchanged.')
