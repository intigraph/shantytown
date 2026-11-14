"""Recipient processing decisions, separate from transport receipt ACKs.

State is local to the configured deployment root. Original inbox records remain
untouched: a defer resurfaces its exact original receipt, never a fresh resend.
"""
from __future__ import annotations

from datetime import datetime
import fcntl
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import re
import time

from .files import write_json_atomic


def identity(message):
    sender = message.frm
    if sender is None:
        match = re.match(r'^\[from ([a-zA-Z0-9_-]+)\] ', message.body)
        sender = match.group(1) if match else None
    value = [message.to, sender, message.body]
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()


def deadline(value, *, now=None):
    if not isinstance(value, str):
        raise ValueError('--defer-id requires --until')
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('defer deadline requires an explicit timezone')
    result = stamp.timestamp()
    now = time.time() if now is None else now
    if not math.isfinite(result) or not 0 < result - now <= 30 * 86400:
        raise ValueError('defer deadline must be in the next 30 days')
    return result


class Dispositions:
    def __init__(self, root, backend):
        # A backend flip must not suppress records from another inbox store.
        self.directory = Path(root) / 'inbox-dispositions' / backend

    def _path(self, message):
        return self.directory / (identity(message) + '.json')

    def get(self, message):
        path = self._path(message)
        try:
            value = json.loads(path.read_text())
        except FileNotFoundError:
            return None
        if (not isinstance(value, dict) or value.get('schema') != 1
                or value.get('identity') != identity(message)
                or value.get('recipient') != message.to
                or value.get('state') not in ('ack', 'defer')
                or not isinstance(value.get('receipt'), str) or not value['receipt']
                or not isinstance(value.get('reason'), str) or not value['reason'].strip()
                or type(value.get('created')) not in (int, float)
                or not math.isfinite(value['created'])):
            raise ValueError('inbox disposition UNKNOWN; malformed binding')
        until = value.get('until')
        if value['state'] == 'defer' and (type(until) not in (int, float)
                or not math.isfinite(until) or not 0 < until - value['created'] <= 30 * 86400):
            raise ValueError('inbox disposition UNKNOWN; malformed deadline')
        return value

    def set(self, message, state, reason, *, until=None, now=None):
        if state not in ('ack', 'defer') or not reason.strip() or len(reason.encode()) > 1024:
            raise ValueError('bounded nonempty processing reason required')
        now = time.time() if now is None else now
        if not math.isfinite(now):
            raise ValueError('clock UNKNOWN')
        if state == 'defer' and (type(until) not in (int, float)
                or not math.isfinite(until) or not 0 < until - now <= 30 * 86400):
            raise ValueError('defer deadline must be in the next 30 days')
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.directory / '.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.get(message)  # A malformed prior decision is not overwritten.
            if not self._path(message).exists() and sum(1 for _ in self.directory.glob('*.json')) >= 1024:
                raise ValueError('inbox disposition capacity reached (1024)')
            value = dict(schema=1, identity=identity(message), recipient=message.to,
                         receipt=message.id, state=state, reason=reason,
                         created=now, until=until if state == 'defer' else None)
            write_json_atomic(self._path(message), value)
            if self.get(message) != value:
                raise RuntimeError('inbox disposition readback UNKNOWN')
            return value

    def due(self, me, box, *, now=None):
        now = time.time() if now is None else now
        if not self.directory.exists():
            return []
        paths = list(self.directory.glob('*.json'))
        if len(paths) > 1024:
            raise ValueError('inbox disposition capacity UNKNOWN; inspect controls')
        result = []
        for path in sorted(paths):
            row = json.loads(path.read_text())
            if not isinstance(row, dict):
                raise ValueError('malformed inbox disposition')
            if row.get('recipient') != me or row.get('state') != 'defer':
                continue
            until = row.get('until')
            if type(until) not in (int, float) or not math.isfinite(until):
                raise ValueError('defer deadline UNKNOWN')
            if now < until:
                continue
            if len(result) >= 64:
                raise ValueError('due inbox dispositions exceed 64-receipt read budget')
            message = box.get_message(me, row['receipt'])
            if message is None or self._path(message) != path or self.get(message) != row:
                raise ValueError('deferred receipt binding UNKNOWN')
            result.append(replace(message, read=False))
        return result

    def visible(self, message, *, now=None):
        row = self.get(message)
        if row is None:
            return True
        # Exact duplicates stay quiet after expiry. Only the original durable
        # unread pointer wakes once; ordinary receipt ACK retires that pointer.
        return (row['state'] == 'defer' and message.id == row['receipt']
                and (time.time() if now is None else now) >= row['until'])


class ControlledInbox:
    """Read presentation only; stored counts and receipt proofs stay unchanged."""
    def __init__(self, box, dispositions):
        self.raw = box
        self.dispositions = dispositions

    def __getattr__(self, name):
        return getattr(self.raw, name)

    def _visible(self, me, rows):
        due = self.dispositions.due(me, self.raw)
        selected = {m.id: m for m in due}
        for message in rows:
            if self.dispositions.visible(message):
                selected.setdefault(message.id, message)
        return list(selected.values())

    def unread(self, me):
        return self._visible(me, self.raw.unread(me))

    def unread_count(self, me):
        counter = getattr(self.raw, 'unread_count', None)
        return counter(me) if callable(counter) else len(self.raw.unread(me))

    def unread_view(self, me, *, limit=100, oldest_first=False):
        view = getattr(self.raw, 'unread_view', None)
        if callable(view):
            total, rows = view(me, limit=limit, oldest_first=oldest_first)
        else:
            rows = self.raw.unread(me)
            total = len(rows)
            rows = rows[:limit]
        visible = self._visible(me, rows)
        # total describes stored rows, not a promise that hidden rows are eligible.
        return max(total, len(visible)), visible[:limit]

    def unread_selected(self, me, ids):
        select = getattr(self.raw, 'unread_selected', None)
        rows = select(me, ids) if callable(select) else self.raw.unread(me)
        return [m for m in self._visible(me, rows) if m.id in ids]

    def mark_read(self, me, ids=None):
        due = [m for m in self.dispositions.due(me, self.raw)
               if ids is None or m.id in ids]
        marked = self.raw.mark_read(me, ids)
        for message in due:
            self.dispositions.set(message, 'ack',
                'deferred receipt presented and acknowledged; original evidence retained')
        return list({m.id: m for m in marked + [replace(m, read=True) for m in due]}.values())
