"""Root-private, bounded own-job messages; never a controller-ledger writer.

The fixed helper authenticates its sudo caller against a protected manifest
before entering this module. Results carry no signing or merge authority.
"""
from __future__ import annotations

import fcntl
import json
import math
import os
import re
import stat
from pathlib import Path

from .actor_identity import IdentityError

MAX_BYTES = 512 * 1024
MAX_TURNS = 4096


def payload(value):
    if not isinstance(value, dict) or value.get('kind') not in ('report', 'turn'):
        raise IdentityError('invalid job message')
    if value['kind'] == 'report':
        if (set(value) not in ({'kind', 'verdict', 'summary'}, {'kind', 'verdict', 'summary', 'review'})
                or value['verdict'] not in ('approve', 'request-changes', 'merged', 'blocked', 'done', 'failed')
                or not isinstance(value['summary'], str) or len(value['summary']) > 1500
                or '\0' in value['summary']):
            raise IdentityError('invalid job result')
        if 'review' in value:
            proof = value['review']
            if (not isinstance(proof, dict) or set(proof) != {'record', 'head', 'signer'}
                    or any(not isinstance(v, str) or len(v) > 256 for v in proof.values())
                    or not re.fullmatch(r'[0-9a-f]{40}', proof['head'])
                    or not re.fullmatch(r'http://aegis\.gastown\.local/ontology/gate_approval\.[0-9a-f]{32}', proof['record'])
                    or not re.fullmatch(r'st-job-verifier\.eph-review-[0-9a-f]{6}', proof['signer'])):
                raise IdentityError('invalid job review proof reference')
    else:
        if (set(value) != {'kind', 'token', 'context_k'}
                or not isinstance(value['token'], str) or not re.fullmatch(r'[0-9a-f]{64}', value['token'])
                or value['context_k'] is not None and (type(value['context_k']) not in (int, float)
                    or not math.isfinite(value['context_k']) or value['context_k'] < 0)):
            raise IdentityError('invalid job turn')
    return value


def read(base, spec, digest, *, trust):
    path = Path(base) / 'messages' / (spec['principal'] + '.json')
    trust(path.parent, directory=True)
    try:
        trust(path)
    except FileNotFoundError:
        return {'version': 1, 'uid': spec['uid'], 'sha256': digest, 'turns': {}, 'result': None}
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        meta = os.fstat(stream.fileno())
        if not stat.S_ISREG(meta.st_mode) or meta.st_mode & 0o077 or meta.st_size > MAX_BYTES:
            raise IdentityError('invalid private job mailbox')
        state = json.load(stream)
    return validate(state, spec, digest)


def validate(state, spec, digest):
    if (not isinstance(state, dict) or set(state) != {'version', 'uid', 'sha256', 'turns', 'result'}
            or type(state['version']) is not int or state['version'] != 1
            or type(state['uid']) is not int or state['uid'] != spec['uid'] or state['sha256'] != digest
            or not isinstance(state['turns'], dict) or len(state['turns']) > MAX_TURNS):
        raise IdentityError('mailbox binding or state changed')
    for token, context in state['turns'].items():
        payload({'kind': 'turn', 'token': token, 'context_k': context})
    if state['result'] is not None:
        payload(state['result'])
        if state['result']['kind'] != 'report':
            raise IdentityError('invalid retained job result')
    return state


def submit(base, spec, digest, value, *, trust, owner=0):
    value = payload(value)
    directory = Path(base) / 'messages'
    trust(directory, directory=True)
    fd = os.open(directory / '.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'r+') as lock:
        meta = os.fstat(lock.fileno())
        if meta.st_uid != owner or not stat.S_ISREG(meta.st_mode) or meta.st_mode & 0o077:
            raise IdentityError('invalid protected job mailbox lock')
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = read(base, spec, digest, trust=trust)
        if value['kind'] == 'report':
            if state['result'] is not None and state['result'] != value:
                raise IdentityError('job result already submitted; no replacement')
            state['result'] = value
        else:
            token = value['token']
            if token in state['turns']:
                if state['turns'][token] != value['context_k']:
                    raise IdentityError('job turn token reused with different content')
            elif len(state['turns']) >= MAX_TURNS:
                raise IdentityError('job turn mailbox exhausted')
            else:
                state['turns'][token] = value['context_k']
        raw = json.dumps(state, sort_keys=True).encode()
        if len(raw) > MAX_BYTES:
            raise IdentityError('job mailbox exceeds its bound')
        # A private fixed temp file under the immutable directory; do not adopt
        # an interrupted/unverified temp file. Lock serializes all submissions.
        target = directory / (spec['principal'] + '.json')
        temporary = target.with_suffix('.pending')
        out = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(out, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            parent = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
        except BaseException:
            # Preserve a possible partial record for explicit recovery; no
            # automatic deletion/retry can manufacture an acknowledged result.
            raise
    return state
