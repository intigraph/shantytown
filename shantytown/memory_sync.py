"""One bounded synchronization step, with a durable active batch and head.

This is a library for a future ordinary lifecycle trigger, not an installed
hook or native selector. The lock coordinates cooperating processes sharing
one private outbox; it cannot exclude another writer with the same OS UID.
Source capture is deferred until there is no active frozen batch. An unknown
outcome retains that exact batch and never adopts an unrelated remote head.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
import re
import secrets
import stat

from . import memory_batch
from .memory_outbox import Outbox, _bytes
from .memory_remote import Unproven, _json, _export_files

_STATE = 'memory-sync.json'
_LOCK = 'memory-sync.lock'
_BATCH = re.compile(r'batch-[a-f0-9]{64}\.json\Z')
_HEAD = re.compile(r'urn:quipu:memory:snapshot:[a-f0-9]{64}\Z')


@contextmanager
def _locked(outbox):
    directory = outbox._open()
    lock = None
    try:
        outbox._install(directory, _LOCK, b'')
        lock = os.open(_LOCK, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        info = os.fstat(lock)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or info.st_mode & 0o077 or info.st_size):
            raise Unproven('unsafe memory synchronization lock')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Unproven('memory synchronization already active') from None
        yield directory
    finally:
        if lock is not None:
            os.close(lock)
        os.close(directory)


def _load(outbox, fd):
    raw = outbox._read(fd, _STATE)
    if raw is None:
        return raw, dict(format='shantytown.memory-sync/v1', owner=outbox.owner.wire(),
                         accepted_head=None, active_batch=None)
    state = _json(raw)
    if (not isinstance(state, dict)
            or set(state) != {'format', 'owner', 'accepted_head', 'active_batch'}
            or state['format'] != 'shantytown.memory-sync/v1'
            or state['owner'] != outbox.owner.wire()
            or not _optional(state['accepted_head'], _HEAD)
            or not _optional(state['active_batch'], _BATCH)):
        raise Unproven('memory synchronization state unproven')
    return raw, state


def _optional(value, pattern):
    return value is None or isinstance(value, str) and pattern.fullmatch(value) is not None


def _save(outbox, fd, previous, state):
    # Atomic rename avoids a torn journal on crash. The expected-byte check
    # supplements the cooperative lock; it is not a same-UID security barrier.
    if outbox._read(fd, _STATE) != previous:
        raise Unproven('memory synchronization state changed; preserve batch')
    raw = _bytes(state)
    temporary = 'memory-sync-' + secrets.token_hex(16) + '.tmp'
    outbox._install(fd, temporary, raw)
    try:
        if outbox._read(fd, _STATE) != previous:
            raise Unproven('memory synchronization state changed; preserve batch')
        os.replace(temporary, _STATE, src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
        if outbox._read(fd, _STATE) != raw:
            raise Unproven('memory synchronization durable readback differs')
    finally:
        try:
            os.unlink(temporary, dir_fd=fd)
        except FileNotFoundError:
            pass
    return raw


def _projection(client):
    result = client.projection()
    if (not isinstance(result, dict)
            or result.get('authenticated_owner') != client.owner.crew
            or not isinstance(result.get('export'), dict)):
        raise Unproven('own memory synchronization identity unproven')
    _export_files(result['export'], client.owner, allow_empty=True)
    snapshot = result['export']['snapshot']
    head = snapshot.get('revision') if snapshot is not None else None
    if not _optional(head, _HEAD) or snapshot is not None and head is None:
        raise Unproven('memory synchronization head unproven')
    return result, head


def step(outbox: Outbox, client, capture, *, harness, account, max_new=1):
    """Resume before recapture; make at most max_new pending-intent attempts.

    capture is a bounded source snapshot callable. Never select a new native
    root here. A completed batch advances the journal only after a fresh named
    own projection proves the final committed head, not just receipt existence.
    """
    if client.owner != outbox.owner:
        raise Unproven('memory synchronization owner mismatch')
    if type(max_new) is not int or not 0 <= max_new <= memory_batch.MAX_FILES:
        raise Unproven('memory synchronization delivery budget invalid')
    with _locked(outbox) as fd:
        raw, state = _load(outbox, fd)
        if state['active_batch'] is None:
            projection, head = _projection(client)
            if head != state['accepted_head']:
                raise Unproven('remote memory head differs; no automatic adoption')
            requests = memory_batch.plan(outbox.owner, capture(),
                projection if head is not None else None, harness=harness, account=account)
            if not requests:
                return dict(status='unchanged', accepted_head=head, remaining=0,
                            native_selection='UNCHANGED')
            state['active_batch'] = memory_batch.freeze(outbox, requests)
            raw = _save(outbox, fd, raw, state)
        result = memory_batch.deliver(outbox, state['active_batch'], client, max_new=max_new)
        if result['remaining']:
            return dict(status='pending', remaining=result['remaining'],
                        accepted_head=state['accepted_head'], native_selection='UNCHANGED')
        if not result['receipts']:
            raise Unproven('active memory batch has no accepted intents')
        expected = result['receipts'][-1]['snapshot']
        _, head = _projection(client)
        if head != expected:
            raise Unproven('final memory head differs; active batch retained')
        state.update(accepted_head=head, active_batch=None)
        _save(outbox, fd, raw, state)
        return dict(status='accepted', accepted_head=head, remaining=0,
                    native_selection='UNCHANGED')
