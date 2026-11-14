"""Release a terminal composer reservation only after native work is unheld.

# arming: agent-invoked; explicit operator receipt, read-only unless --apply.
This does not prove delivery, assign work, send a message, or certify health.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import time

from . import refill_reconcile as rr
from .delivery import Custody
from .files import FilesRegistry

FIELDS = {'version', 'worker', 'item', 'pending', 'custody', 'custody_sha256'}


def validate(request):
    rr.require(isinstance(request, dict) and set(request) == FIELDS,
               'unsupported terminal receipt fields')
    rr.require(type(request['version']) is int and request['version'] == 1,
               'unsupported terminal receipt version')
    for key, pattern in [('worker', rr.NAME), ('item', rr.ITEM),
                         ('custody_sha256', rr.DIGEST)]:
        rr.require(isinstance(request[key], str) and pattern.fullmatch(request[key]),
                   'invalid terminal receipt identity')
    rr.require(re.fullmatch(r'send-[0-9a-f]{32}', str(request['custody'])),
               'invalid custody ID')
    pending = request['pending']
    rr.require(isinstance(pending, dict) and set(pending) in
               ({'item', 'at'}, {'item', 'at', 'lane'}), 'unsupported reservation fields')
    rr.require(pending['item'] == request['item'] and rr.number(pending['at'])
               and pending['at'] > 0, 'invalid exact reservation')
    rr.require('lane' not in pending or pending['lane'] in ('now', 'next', 'later'),
               'invalid reservation lane')


def native_tracker(root):
    # The deployed adapter selects its own backend/store. Never initialize a
    # fallback store or accept an operator-supplied JSON row as native proof.
    from .feed_check import TrackerAdapter
    tracker = TrackerAdapter(root, FilesRegistry(root / 'crew'))
    rr.require(tracker.tracker is not None, 'native tracker backend unsupported')
    return tracker


def unheld(tracker, item):
    row = tracker.show(item).exact()
    rr.require(isinstance(row, dict) and row.get('id') == item,
               'native tracker item identity unknown')
    rr.require('assignee' in row and type(row.get('revision')) is int
               and row['revision'] >= 0, 'native ownership/revision unknown')
    owner, status = row['assignee'], row.get('status')
    rr.require(owner is None or isinstance(owner, str), 'native owner malformed')
    rr.require(status == 'closed' or
               (status in ('open', 'deferred', 'blocked') and owner in (None, '')),
               'native work is still held or status is unknown')
    return {key: row[key] for key in ('id', 'status', 'assignee', 'revision')}


def qualified(root, request, tracker):
    ident = rr.digest(json.dumps(request, sort_keys=True, separators=(',', ':')).encode())
    path = root / 'delivery' / (request['custody'] + '.json')
    rr.owned(path)
    with path.open('rb') as stream:
        raw = stream.read(rr.MAX_JSON + 1)
    rr.require(len(raw) <= rr.MAX_JSON, 'terminal custody exceeds bound')
    record = rr.decode(raw)
    rr.require(rr.digest(raw) == request['custody_sha256'],
               'terminal custody bytes changed')
    rr.require(record.get('id') == request['custody'] and
               record.get('state') in ('orphaned', 'dequeued') and
               record.get('pointer_state') == 'recorded' and
               isinstance(record.get('pointer'), str) and record['pointer'] and
               isinstance(record.get('pane'), str) and record['pane'],
               'terminal composer custody/pointer unknown')
    rr.require(not record.get('refill_receipt'), 'custody already has delivery reconciliation')
    body = record.get('text', '')
    rr.require(isinstance(body, str) and
               body.startswith('Work is on your hook: ' + request['item'] + ' — ') and
               re.search(r'\[st serve:[0-9a-f]{32} worker:' +
                         re.escape(request['worker']) + r'\]$', body),
               'terminal dispatch binding absent')
    rr.require(rr.number(record.get('created')) and rr.number(record.get('session'))
               and record['session'] <= record['created']
               and request['pending']['at'] <= record['created'] <= time.time(),
               'terminal dispatch time binding unknown')
    state = rr.read(root / 'refill/state.json')
    rr.require(isinstance(state.get('pending'), dict), 'refill reservations unreadable')
    journal = root / 'refill/terminal-reconciliations.jsonl'
    entries = [row for row in rr.audit_rows(journal) if row.get('receipt_id') == ident]
    rr.require([row.get('event') for row in entries] in
               ([], ['prepared'], ['prepared', 'completed']), 'terminal audit ambiguous')
    if entries:
        prepared = entries[0]
        rr.require(prepared.get('request') == request and
                   prepared.get('original_custody') == record and
                   prepared.get('original_pending') == request['pending'],
                   'terminal audit evidence changed')
    pending = state['pending'].get(request['worker'])
    rr.require(pending == request['pending'] or (pending is None and entries),
               'exact reservation changed or absent without audit')
    done = len(entries) == 2
    rr.require(not done or pending is None, 'completed terminal audit conflicts with reservation')
    proof = unheld(tracker, request['item'])
    rr.require(not entries or entries[0].get('tracker') == proof,
               'native ownership changed after preparation')
    result = dict(state='already-reconciled' if done else 'qualified', receipt_id=ident,
                  worker=request['worker'], item=request['item'], tracker=proof,
                  delivery='UNKNOWN', custody_state=record['state'])
    return result, state, record, journal, entries


def reconcile(root, request, *, apply=False, tracker=None):
    root = Path(root).absolute()
    rr.require(root.resolve() == root, 'deployment root must be canonical')
    rr.owned(root, directory=True)
    for name in ('refill', 'crew', 'delivery'):
        rr.owned(root / name, directory=True)
    validate(request)
    tracker = native_tracker(root) if tracker is None else tracker
    initial = qualified(root, request, tracker)[0]
    if not apply:
        return initial
    with rr.reservation_lock(root):
        record = rr.read(root / 'delivery' / (request['custody'] + '.json'))
        with Custody(root, record['pane'], record.get('socket')):
            result, state, record, journal, entries = qualified(root, request, tracker)
            if result['state'] == 'already-reconciled':
                return result
            if not entries:
                rr.append(journal, dict(event='prepared', receipt_id=result['receipt_id'],
                          request=request, original_custody=record,
                          original_pending=request['pending'], tracker=result['tracker']))
                rr.sync_directory(journal.parent)
            rr.require(rr.read(root / 'refill/state.json') == state,
                       'refill state changed under lock')
            rr.require(rr.read(root / 'delivery' / (request['custody'] + '.json')) == record,
                       'terminal custody changed under lock')
            rr.require(unheld(tracker, request['item']) == result['tracker'],
                       'native ownership changed before release')
            if request['worker'] in state['pending']:
                del state['pending'][request['worker']]
                rr.replace(root / 'refill/state.json', state)
            rr.append(journal, dict(event='completed', receipt_id=result['receipt_id']))
            return dict(result, state='reconciled')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--receipt', required=True, type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = reconcile(args.root, rr.read(args.receipt), apply=args.apply)
    except Exception:
        # Adapter errors can contain private service diagnostics. UNKNOWN is a
        # refusal, not permission to try another backend or clear a reservation.
        print(json.dumps(dict(state='refused', reason='terminal custody/native ownership unqualified')))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
