"""Scope custody across the send/claim boundary; never a delivery queue.

The transport's existing Custody owns composer recovery. This ledger owns the
separate question of which immutable scope a tracker assignment acknowledges.
# arming: library; dispatch integration supplies native CAS/read-back callbacks.
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
import threading
from functools import wraps
import uuid

from .protocols import SubmissionObserved

FIELDS = ('item', 'revision', 'worker', 'pane', 'session', 'task_sha256', 'scope_sha256')


class ReceiptConflict(ValueError):
    """No submission, assignment or replay is authorized by this receipt."""


def serialized_receipt(method):
    @wraps(method)
    def guarded(self, ident, *args, **kwargs):
        row = self.read(ident)
        with self.lock(row['item']):
            return method(self, ident, *args, **kwargs)
    return guarded


class ReceiptStore:
    def __init__(self, root):
        # Construction and status are reads, including when no ledger exists.
        self.root = Path(root) / 'dispatch-receipts'
        self._local = threading.local()

    def _directory(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.is_symlink() or self.root.stat().st_uid != os.getuid():
            raise ReceiptConflict('dispatch receipt directory ownership unproven')
        os.chmod(self.root, 0o700)

    @contextmanager
    def lock(self, item):
        held = getattr(self._local, 'items', set())
        if item in held:
            yield
            return
        self._directory()
        name = hashlib.sha256(item.encode()).hexdigest() + '.lock'
        fd = os.open(self.root / name, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'a') as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ReceiptConflict('another dispatch owns this item') from None
            self._local.items = held | {item}
            try:
                yield
            finally:
                self._local.items = held

    def _path(self, ident):
        if not isinstance(ident, str) or not re.fullmatch(r'[0-9a-f]{32}', ident):
            raise ReceiptConflict('invalid dispatch receipt ID')
        return self.root / (ident + '.json')

    def read(self, ident):
        path = self._path(ident)
        if self.root.is_symlink() or path.is_symlink():
            raise ReceiptConflict('dispatch receipt is a symlink')
        if path.stat().st_uid != os.getuid():
            raise ReceiptConflict('dispatch receipt owner changed')
        row = json.loads(path.read_text())
        if (row.get('id') != ident or row.get('state') not in
                {'prepared', 'submitted', 'assigning', 'assigned'}):
            raise ReceiptConflict('dispatch receipt malformed')
        self._scope(row)
        if hashlib.sha256(row['text'].encode()).hexdigest() != row['body_sha256']:
            raise ReceiptConflict('dispatch receipt body changed')
        return row

    def _save(self, row):
        self._directory()
        fd, name = tempfile.mkstemp(dir=self.root, prefix='.pending-')
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(row, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self._path(row['id']))
            folder = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(folder)
            finally:
                os.close(folder)
        finally:
            if os.path.exists(name):
                os.unlink(name)
        return copy.deepcopy(row)

    @staticmethod
    def _scope(value):
        if (type(value.get('revision')) is not int or value['revision'] < 1
                or type(value.get('session')) not in (int, float)
                or not math.isfinite(value['session']) or not value['session'] > 0
                or any(not isinstance(value.get(k), str) or not value[k]
                       for k in FIELDS if k not in ('revision', 'session'))):
            raise ReceiptConflict('dispatch task revision, scope or runtime identity UNKNOWN')
        return {key: value[key] for key in FIELDS}

    def prepare(self, scope, text):
        scope = self._scope(scope)
        with self.lock(scope['item']):
            return self._prepare(scope, text)

    def _prepare(self, scope, text):
        """Caller holds the item lock; return the original attempt on replay.

        No pending attempt can be replaced by a changed task, worker or note.
        A coordinator must reconcile its retained evidence before another send.
        """
        scope = self._scope(scope)
        paths = list(self.root.glob('*.json'))
        if len(paths) > 4096:
            raise ReceiptConflict('dispatch receipt coverage bound exceeded')
        rows = [self.read(p.stem) for p in paths]
        rows = [r for r in rows if r['item'] == scope['item']]
        pending = [r for r in rows if r['state'] != 'assigned']
        if len(pending) > 1:
            raise ReceiptConflict('ambiguous pending dispatch; reconcile receipts')
        for row in pending + sorted(rows, key=lambda r: r['created'], reverse=True):
            if self._scope(row) == scope or self._assigned_scope(row, scope):
                if row['text'] != text:
                    raise ReceiptConflict('same scope has a different body; reconcile receipt')
                return row, False
            if row in pending:
                raise ReceiptConflict('pending dispatch has a different scope; reconcile receipt')
        row = dict(scope, id=uuid.uuid4().hex, text=text,
                   body_sha256=hashlib.sha256(text.encode()).hexdigest(),
                   created=time.time(), state='prepared', submission=None, assignment=None)
        return self._save(row), True

    @serialized_receipt
    def submitted(self, ident, evidence):
        row = self.read(ident)
        if not isinstance(evidence, SubmissionObserved) or not evidence.matches(row['pane'], row['text']):
            raise ReceiptConflict('submission proof does not match this receipt body and pane')
        if row['submission'] is not None:
            return row
        row['submission'] = dict(kind='adapter-exact-body', at=time.time())
        row['state'] = 'submitted'
        return self._save(row)

    @serialized_receipt
    def assign(self, ident, current, claim):
        """Invoke ONE native revision-guarded claim, never retry its uncertainty.

        claim(row) must atomically bind row.id in the native transition and
        return its read-back proof. A process exit/status/owner alone is not it.
        These are backend callbacks, never a CLI-supplied proof or manual claim.
        """
        row = self.read(ident)
        if self._scope(row) != self._scope(current) and not self._assigned_scope(row, current):
            raise ReceiptConflict('stale task, worker, runtime or scope')
        if row['state'] == 'assigned':
            return row
        if row['state'] == 'assigning':
            raise ReceiptConflict('assignment outcome UNKNOWN; reconcile native receipt before retry')
        if row['submission'] is None:
            raise ReceiptConflict('submission unconfirmed; no assignment authorized')
        row['state'] = 'assigning'
        self._save(row)  # An interrupt after this point cannot repeat the claim.
        proof = claim(copy.deepcopy(row))
        return self.recover_assignment(ident, proof)

    @serialized_receipt
    def recover_assignment(self, ident, proof):
        """Only a native read-back carrying this exact receipt repairs a claim."""
        row = self.read(ident)
        if (row['state'] not in ('assigning', 'assigned')
                or not isinstance(proof, dict) or proof.get('receipt') != ident
                or type(proof.get('revision')) is not int
                or proof['revision'] <= row['revision']):
            raise ReceiptConflict('native assignment receipt proof incomplete')
        if row['state'] == 'assigned':
            if proof != row['assignment']:
                raise ReceiptConflict('native assignment receipt proof changed')
            return row
        row['state'], row['assignment'] = 'assigned', copy.deepcopy(proof)
        return self._save(row)

    def _assigned_scope(self, row, current):
        current = self._scope(current)
        expected = self._scope(row)
        if row['state'] != 'assigned' or not row['assignment']:
            return False
        expected['revision'] = row['assignment']['revision']
        return expected == current

    def status(self, ident, current):
        """Read-only: report missing evidence without sending or claiming work."""
        row = self.read(ident)
        fresh = (self._assigned_scope(row, current) if row['state'] == 'assigned'
                 else self._scope(row) == self._scope(current))
        missing = ([] if row['submission'] else ['submission'])
        if not row['assignment']:
            missing.append('assignment')
        return dict(id=ident, state=row['state'] if fresh else 'stale',
                    missing=missing, execution_authorized=fresh and not missing)
