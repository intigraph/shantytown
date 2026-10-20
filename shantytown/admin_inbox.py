"""Opt-in routine inbox batching; no prompt-text or operator-identity guessing.

# arming: library; the existing fleet tend schedule drains persisted pointers.
Only pointers/hashes live here. The configured inbox retains bodies and ACKs.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
from pathlib import Path
import time

from .files import write_json_atomic


def wait_for(root, card, *, now=None):
    """Same fresh Claude lane/cadence as Stop; unknown evidence is immediate."""
    from . import config, feed_check
    from .admin_wake_budget import remaining
    from .harness import for_card
    from .hibernate import WakeLog
    try:
        cfg, error = config.load_or_default(root)
        policy = cfg.admin_wake_budget
        if (error or policy.mode != 'enforce' or card.name not in policy.agents
                or card.role != 'administrator'
                or for_card(card, root=root).name != 'claude'):
            return 0
        verdict = feed_check.haul_governor_verdict(root, card)
        last = WakeLog(root).last(card.name)
        if verdict is None or verdict.signal_lost or last is None:
            return 0
        return remaining(verdict.by_window.get('seven_day'),
                         (time.time() if now is None else now) - last)
    except Exception:
        return 0


def _directory(root):
    return Path(root) / 'admin-wake-budget' / 'routine-inbox'


@contextmanager
def _locked(root):
    directory = _directory(root)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'queue.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield directory


def enqueue(root, card, item, backend, wait, *, now=None):
    """Persist already-durable receipt before withholding its live nudge."""
    now = time.time() if now is None else now
    if not math.isfinite(now) or not math.isfinite(wait) or not 0 < wait <= 900:
        raise ValueError('routine deadline unknown')
    value = dict(id=item.id, recipient=card.name, backend=backend,
                 pane=card.pane, host=getattr(card, 'host', None),
                 body_hash=hashlib.sha256(item.body.encode()).hexdigest(),
                 created=now, due=now + wait, state='pending')
    key = hashlib.sha256(json.dumps([backend, card.name, item.id]).encode()).hexdigest()
    with _locked(root) as directory:
        path = directory / (key + '.json')
        if path.exists():
            raise ValueError('routine receipt already scheduled; do not resubmit')
        if sum(1 for _ in directory.glob('*.json')) >= 256:
            raise ValueError('routine queue capacity reached')
        write_json_atomic(path, value)


def sweep(root, agents, panes, box_for, *, now=None, log=lambda message: None):
    """One batch per recipient/backend, one live attempt; uncertain ACK retains mail.

    A crash after claim cannot authorize another live send. The durable inbox
    pointer remains available to normal reads/startup, including after restart.
    No offline session is started and no remote relay is introduced.
    """
    directory = _directory(root)
    if not directory.exists():
        return []
    now = time.time() if now is None else now
    if not math.isfinite(now):
        raise ValueError('routine clock unknown')
    cards = {card.name: card for card in agents}
    sent = []
    with _locked(root):
        groups = {}
        for path in sorted(directory.glob('*.json'))[:256]:
            row = json.loads(path.read_text())
            if row['state'] != 'pending':
                continue
            if (not math.isfinite(row['due']) or not math.isfinite(row['created'])
                    or not 0 < row['due'] - row['created'] <= 900):
                raise ValueError('routine deadline evidence malformed')
            card = cards.get(row['recipient'])
            if card is None or getattr(card, 'retired', False):
                continue
            if card.pane != row['pane'] or getattr(card, 'host', None) != row['host']:
                log(f'routine inbox: {card.name} recipient binding changed; pointer retained')
                continue
            # OFF/advice/unknown policy releases early. A clock reversal also
            # releases, rather than extending the original promised cadence.
            if row['created'] <= now < row['due'] and wait_for(root, card, now=now):
                continue
            groups.setdefault((card.name, row['backend']), []).append((path, row))
        for (name, backend), entries in groups.items():
            card = cards[name]
            if not card.pane or not panes.exists(card.pane):
                continue
            box = box_for(backend)
            unread = {msg.id: msg for msg in box.unread(name)}
            ready = []
            for path, row in sorted(entries, key=lambda entry: (entry[1]['created'], entry[1]['id']))[:20]:
                msg = unread.get(row['id'])
                if msg is None:
                    # Missing from this reader is not proof of an ACK.
                    log(f'routine inbox: {name}/{row["id"]} unread coverage UNKNOWN')
                    continue
                if hashlib.sha256(msg.body.encode()).hexdigest() != row['body_hash']:
                    log(f'routine inbox: {name}/{msg.id} body mismatch; retained')
                    continue
                row['state'] = 'attempted'
                write_json_atomic(path, row)
                ready.append((path, msg))
            if not ready:
                continue
            body = '\n\n'.join(msg.body for _, msg in ready)
            try:
                panes.send(card.pane, body)
                # Same conservative post-send composer check as durable inbox.
                from .cli import _looks_stranded
                if _looks_stranded(panes, card.pane):
                    raise RuntimeError('live input remains stranded')
                box.mark_read(name, ids=[msg.id for _, msg in ready])
            except Exception as error:
                log(f'routine inbox: {name} live/ACK UNKNOWN ({type(error).__name__}); '
                    'durable pointers retained, no automatic resend')
                continue
            for path, msg in ready:
                path.unlink()
                sent.append((name, msg.id))
            log(f'routine inbox: {name} batch delivered and ACKed {len(ready)} pointer(s)')
    return sent
