"""Explicit, receipt-bound release of one uncertain refill; never send or tick.

# arming: agent-invoked; an operator supplies an existing native delivery receipt.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile
import time

from .delivery import Custody
from .files import FilesRegistry

MAX_JSON = 2 * 1024 * 1024
MAX_HISTORY = 256 * 1024 * 1024
NAME = re.compile(r"[a-z][a-z0-9_-]{0,79}")
ITEM = re.compile(r"[a-z][a-z0-9-]{1,79}(?:\.[0-9]+)*")
HISTORY = re.compile(r"[A-Za-z0-9_.-]+\.jsonl")
DIGEST = re.compile(r"[0-9a-f]{64}")
FIELDS = {"version", "worker", "item", "pending_at", "custody", "history", "line", "event_sha256"}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def decode(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs)


def owned(path, *, directory=False):
    info = path.lstat()
    require(info.st_uid == os.getuid() and not stat.S_ISLNK(info.st_mode),
            "receipt/state path must be locally owned and not a symlink")
    require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode),
            "receipt/state path has wrong file kind")
    # Registry/state files use the deployment's normal shared-group modes.
    # Reconciliation neither chmods those files nor requires a permission repair.
    require(not info.st_mode & 0o002, "receipt/state path is world-writable")
    return info


def read(path):
    owned(path)
    with path.open('rb') as stream:
        raw = stream.read(MAX_JSON + 1)
    require(len(raw) <= MAX_JSON, "JSON receipt/state exceeds bound")
    return decode(raw)


def stamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(result.tzinfo is not None, "native timestamp has no timezone")
    return result.timestamp()


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_request(request):
    require(isinstance(request, dict) and set(request) == FIELDS, "unsupported receipt fields")
    require(type(request['version']) is int and request['version'] == 1, "unsupported receipt version")
    for key, pattern in [('worker', NAME), ('item', ITEM), ('history', HISTORY),
                         ('event_sha256', DIGEST)]:
        require(isinstance(request[key], str) and pattern.fullmatch(request[key]),
                "invalid receipt identity")
    require(re.fullmatch(r'send-[0-9a-f]{32}', str(request['custody'])), "invalid custody ID")
    require(number(request['pending_at']) and request['pending_at'] > 0, "invalid reservation timestamp")
    require(type(request['line']) is int and 1 < request['line'] <= 1_000_000, "invalid native line")


def native(root, request, card, record, now):
    directory = root / 'history' / request['worker']
    owned(root / 'history', directory=True)
    owned(directory, directory=True)
    path = directory / request['history']
    info = owned(path)
    require(info.st_size <= MAX_HISTORY, "native history exceeds bounded reader")
    # Only this pre-existing recipient archive is read; a receipt cannot name an
    # arbitrary path, execute a command, or promote a compacted quotation to input.
    with path.open('rb') as stream:
        first = stream.readline(MAX_JSON + 1)
        require(len(first) <= MAX_JSON, "native metadata exceeds bound")
        meta = decode(first)
        require(meta.get('type') == 'session_meta', "native session metadata absent")
        identity = meta.get('payload', {})
        require(identity.get('cwd') == card.workspace and card.workspace,
                "native session belongs to another workspace")
        require(isinstance(identity.get('id'), str) and
                request['history'].endswith(identity['id'] + '.jsonl'), "native session ID mismatch")
        raw = b''
        for _ in range(1, request['line']):
            raw = stream.readline(MAX_JSON + 1)
            require(raw and len(raw) <= MAX_JSON, "native line missing or exceeds bound")
        require(digest(raw) == request['event_sha256'], "native event hash changed")
        event = decode(raw)
    payload = event.get('payload', {})
    require(event.get('type') == 'response_item' and payload.get('type') == 'message'
            and payload.get('role') == 'user', "receipt is not native accepted user input")
    content = payload.get('content')
    require(isinstance(content, list) and len(content) == 1 and
            content[0].get('type') == 'input_text', "unsupported native input framing")
    require(content[0].get('text') == record['text'], "native input is not the exact dispatch body")
    require(number(record.get('created')) and number(record.get('session')) and
            record['session'] <= record['created'], "custody session/time unavailable")
    received = stamp(event['timestamp'])
    require(stamp(meta['timestamp']) <= record['created'] and
            request['pending_at'] <= record['created'] <= received <= now,
            "receipt predates reservation or is in the future")
    return dict(history=request['history'], line=request['line'], received_at=event['timestamp'],
                event_sha256=request['event_sha256'], body_sha256=digest(record['text'].encode()))


def append(path, value):
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        require(os.fstat(fd).st_uid == os.getuid() and stat.S_ISREG(os.fstat(fd).st_mode)
                and not os.fstat(fd).st_mode & 0o077, "audit is not a private local file")
        data = (json.dumps(value, sort_keys=True) + '\n').encode()
        # One bounded write; a partial/crashed audit refuses on its next read.
        require(os.write(fd, data) == len(data), "incomplete audit append")
        os.fsync(fd)
    finally:
        os.close(fd)


def audit_rows(path):
    if not path.exists():
        return []
    owned(path)
    require(path.stat().st_size <= MAX_JSON, "audit exceeds bounded reader")
    return [decode(line) for line in path.read_bytes().splitlines() if line]


def replace(path, value):
    info = owned(path)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.reconcile-')
    try:
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), stat.S_IMODE(info.st_mode))
            json.dump(value, stream, sort_keys=True, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def reservation_lock(root):
    path = root / 'refill' / 'lock'
    owned(path)
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def reconcile(root, request, *, apply=False, now=None):
    """Qualify only by default. Apply never dispatches, ticks, or certifies health."""
    root = Path(root).absolute()
    require(root.resolve() == root, "deployment root must be canonical")
    owned(root, directory=True)
    for name in ('refill', 'crew', 'delivery'):
        owned(root / name, directory=True)
    validate_request(request)
    now = time.time() if now is None else now
    # Invalid evidence does not even create a composer lock file. Apply checks
    # everything again while holding both normal writer locks.
    initial = qualified(root, request, now)[0]
    if not apply:
        return initial
    # Match the normal refill -> composer lock order. No send/repair callback is
    # available on this path, including after a crash or a repeat invocation.
    with reservation_lock(root):
        card = FilesRegistry(root / 'crew').get(request['worker'])
        record = read(root / 'delivery' / (request['custody'] + '.json'))
        with Custody(root, card.pane, record.get('socket')):
            result, state, record, journal, entries = qualified(root, request, now)
            ident = result['receipt_id']
            if result['state'] == 'already-reconciled':
                return result
            previous = [row for row in entries if row.get('receipt_id') == ident]
            if not previous:
                append(journal, dict(event='prepared', receipt_id=ident, request=request,
                                     native=result['native'], original_custody=record,
                                     original_pending=state['pending'][request['worker']]))
                sync_directory(journal.parent)
            require(read(root / 'refill/state.json') == state, "refill state changed under lock")
            current = read(root / 'delivery' / (request['custody'] + '.json'))
            require(current == record, "delivery custody changed under lock")
            if record.get('refill_receipt') != ident:
                replace(root / 'delivery' / (request['custody'] + '.json'),
                        dict(record, state='delivered', refill_receipt=ident))
            if request['worker'] in state['pending']:
                del state['pending'][request['worker']]
                replace(root / 'refill/state.json', state)
            append(journal, dict(event='completed', receipt_id=ident))
            return dict(result, state='reconciled')


def qualified(root, request, now):
    ident = digest(json.dumps(request, sort_keys=True, separators=(',', ':')).encode())
    state = read(root / 'refill/state.json')
    require(isinstance(state.get('pending'), dict), "refill reservations unreadable")
    record = read(root / 'delivery' / (request['custody'] + '.json'))
    owned(root / 'crew' / (request['worker'] + '.json'))
    card = FilesRegistry(root / 'crew').get(request['worker'])
    require(card.harness == 'codex' and card.pane == record.get('pane'), "recipient/harness mismatch")
    require(record.get('id') == request['custody'], "custody ID mismatch")
    body = record.get('text', '')
    require(body.startswith('Work is on your hook: ' + request['item'] + ' — '), "dispatch item mismatch")
    require(re.search(r'\[st serve:[0-9a-f]{32} worker:' + re.escape(request['worker']) + r'\]$', body),
            "dispatch recipient/serve binding absent")
    proof = native(root, request, card, record, now)
    journal = root / 'refill/reconciliations.jsonl'
    entries = audit_rows(journal)
    previous = [row for row in entries if row.get('receipt_id') == ident]
    prepared = [row for row in previous if row.get('event') == 'prepared']
    expected = dict(item=request['item'], at=request['pending_at'])
    require(not previous or (len(prepared) == 1 and prepared[0].get('request') == request
            and prepared[0].get('original_pending') == expected
            and [row.get('event') for row in previous] in
                (['prepared'], ['prepared', 'completed'])),
            "reconciliation audit is ambiguous")
    allowed = record.get('state') in ('unknown', 'queued') and not record.get('refill_receipt')
    committed = record.get('state') == 'delivered' and record.get('refill_receipt') == ident
    require(allowed or (committed and prepared), "custody is not this unresolved/reconciled delivery")
    if prepared:
        original = prepared[0].get('original_custody')
        require(isinstance(original, dict) and record ==
                (dict(original, state='delivered', refill_receipt=ident) if committed else original),
                "custody differs from the prepared audit")
    pending = state['pending'].get(request['worker'])
    require(pending == expected or (pending is None and committed and prepared),
            "reservation differs or no qualified reservation exists")
    done = any(row.get('event') == 'completed' for row in previous)
    require(not done or (committed and pending is None), "completed audit conflicts with live state")
    result = dict(state='already-reconciled' if done else 'qualified', receipt_id=ident,
                  worker=request['worker'], item=request['item'], native=proof)
    return result, state, record, journal, entries


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--receipt', required=True, type=Path)
    parser.add_argument('--apply', action='store_true', help='apply exactly this qualified receipt; default is read-only')
    args = parser.parse_args(argv)
    try:
        result = reconcile(args.root, read(args.receipt), apply=args.apply)
    except (OSError, ValueError, LookupError, KeyError, TypeError, AttributeError):
        print(json.dumps(dict(state='refused', reason='receipt or custody could not be qualified')))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
