"""Frozen multi-file intents with ordered CAS and replay before stale checks.

This is orchestration metadata in the existing private outbox, not a native
root selector. No missing source file is converted to a tombstone. A partial
batch remains explicitly resumable; it is not reported as a complete sync.
"""
from __future__ import annotations

import hashlib
import json
import os
import re

from .memory_files import MAX_FILES, validate
from .memory_outbox import Outbox, _bytes
from .memory_remote import Unproven, canonical_intent, verified_files, _json

_NAME = re.compile(r'batch-([a-f0-9]{64})\.json\Z')
_INTENT = re.compile(r'intent-[a-f0-9]{64}\.json\Z')


def plan(owner, files, baseline=None, *, harness, account):
    """Build deterministic explicit requests against a verified prior export.

    None means first import expecting an absent owner head, not permission to
    adopt whatever remote head happens to exist. New remote edits therefore
    conflict in the protocol. Empty output means no change against THIS prior
    baseline, not proof of current remote state or source-producer freshness.
    """
    files = tuple(sorted(files, key=lambda file: file.path))
    validate(files)
    if baseline is None:
        previous, heads, expected = (), {}, None
    else:
        previous = verified_files(baseline, owner)
        snapshot = baseline['export']['snapshot']
        expected = snapshot.get('revision')
        if not isinstance(expected, str) or not expected.startswith('urn:quipu:memory:snapshot:'):
            raise Unproven('batch baseline snapshot identity unproven')
        heads = snapshot['files']
    before = {file.path: file for file in previous}
    current = {file.path: file for file in files}
    if before.keys() - current.keys():
        raise Unproven('missing source requires explicit deletion disposition, not an implicit tombstone')
    requests = []
    for file in files:
        if file.path in before and before[file.path].data == file.data:
            continue
        key = hashlib.sha256(_bytes({'owner': owner.wire(), 'path': file.path,
            'snapshot': expected, 'sha256': file.sha256, 'harness': harness, 'account': account})).hexdigest()
        request = canonical_intent(dict(owner=owner.wire(), path=file.path,
            text=file.data.decode('utf-8'), expected_snapshot=expected,
            expected_file=heads.get(file.path, {}).get('revision'),
            idempotency_key='sync-' + key, harness=harness, account=account), owner)
        requests.append(request)
        # Protocol snapshot IDs are content-bound to this canonical intent.
        # Predicting the next CAS head does not claim it has been committed.
        digest = hashlib.sha256(json.dumps(request, ensure_ascii=False,
                                           separators=(',', ':')).encode()).hexdigest()
        expected = 'urn:quipu:memory:snapshot:' + digest
    return tuple(requests)


def freeze(outbox: Outbox, requests):
    """Persist every bounded intent before publishing its immutable batch list."""
    requests = tuple(requests)
    if len(requests) > MAX_FILES:
        raise Unproven('memory batch exceeds file bound')
    names = [outbox.enqueue(request) for request in requests]
    if len(set(names)) != len(names):
        raise Unproven('duplicate memory batch intent')
    value = {'format': 'shantytown.memory-batch/v1', 'owner': outbox.owner.wire(), 'intents': names}
    data = _bytes(value)
    name = 'batch-' + hashlib.sha256(data).hexdigest() + '.json'
    fd = outbox._open()
    try:
        outbox._install(fd, name, data)
    finally:
        os.close(fd)
    return name


def deliver(outbox: Outbox, name, client, *, max_new=MAX_FILES):
    """Resume an explicit frozen batch, stopping at the first unknown/conflict.

    Accepted intents are read back before any stale-head rejection. A response
    loss after a middle commit cannot cause an earlier file to be recommitted.
    Later source changes remain in their original files; this never stages or
    replaces native files and never constructs a new batch from changed input.
    """
    # This bounds pending intent attempts, not a wall-clock deadline. Each
    # attempt can perform a receipt read and one commit, both client-bounded.
    if type(max_new) is not int or not 0 <= max_new <= MAX_FILES:
        raise Unproven('memory batch delivery budget invalid')
    if not isinstance(name, str) or not _NAME.fullmatch(name) or client.owner != outbox.owner:
        raise Unproven('memory batch identity mismatch')
    fd = outbox._open()
    try:
        raw = outbox._read(fd, name)
    finally:
        os.close(fd)
    if raw is None or hashlib.sha256(raw).hexdigest() != _NAME.fullmatch(name)[1]:
        raise Unproven('memory batch is missing or changed')
    value = _json(raw)
    if (not isinstance(value, dict) or set(value) != {'format', 'owner', 'intents'}
            or value['format'] != 'shantytown.memory-batch/v1'
            or value['owner'] != outbox.owner.wire()):
        raise Unproven('memory batch owner or format mismatch')
    names = value['intents']
    if (not isinstance(names, list) or len(names) > MAX_FILES
            or any(not isinstance(n, str) or not _INTENT.fullmatch(n) for n in names)
            or len(set(names)) != len(names)):
        raise Unproven('memory batch coverage unproven')
    receipts, attempted = [], 0
    for intent in names:
        receipt = outbox.accepted(intent, client)
        if receipt is None:
            if attempted == max_new:
                break
            attempted += 1
            receipt = outbox.deliver(intent, client)
        receipts.append(receipt)
    remaining = len(names) - len(receipts)
    status = ('batch_partial' if remaining else 'batch_delivered' if receipts
              else 'no_changes_against_supplied_baseline')
    return {'status': status, 'remaining': remaining,
            'receipts': receipts, 'native_selection': 'UNCHANGED',
            'remote_currentness': 'NOT PROVEN'}
