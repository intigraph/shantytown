"""Review a bounded cost window without resetting its producer history.

The pointer is the only commit point. A successor keeps the prior snapshot
ledger, lifetime accounting and cooldown; predecessor files remain untouched.
Pilot mode pauses again; explicit bounded-continuous mode archives later windows.
Neither mode raises publication caps or resolves uncertain writes.
"""
from __future__ import annotations

import copy
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


POINTER = 'cost-active-generation.json'
GENERATIONS = 'cost-review-generations'
LEGACY = 'cost-active-graph-state.json'
# These identify the reviewed envelope, not a second admission implementation.
# Camayoc remains the authority enforcing every publication budget.
LIMITS = {'snapshots': 1, 'items': 8, 'records': 1000, 'body_bytes': 4 * 1024 * 1024}


def _bytes(path, *, required=False):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        if required:
            raise ValueError(f'missing review evidence: {path.name}') from None
        return None
    with os.fdopen(fd, 'rb') as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 4 * 1024 * 1024:
            raise ValueError('review evidence must be a bounded regular file')
        raw = source.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError('review evidence grew beyond its bound')
        return raw


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate review field')
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError('non-finite JSON')))
    if not isinstance(value, dict):
        raise ValueError('review evidence must be an object')
    return value


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def state_path(root):
    root = Path(root)
    raw = _bytes(root / POINTER)
    if raw is None:
        return root / LEGACY
    pointer = _json(raw)
    generation = pointer.get('generation')
    if type(pointer.get('schema_version')) is not int or pointer['schema_version'] != 1 or not isinstance(generation, str) or not re.fullmatch('[0-9a-f]{64}', generation):
        raise ValueError('invalid cost generation pointer')
    parent = root / GENERATIONS
    folder = parent / generation
    if parent.is_symlink() or folder.is_symlink() or not folder.is_dir():
        raise ValueError('cost generation must be an existing local directory')
    review_raw = _bytes(folder / 'review.json', required=True)
    if hashlib.sha256(review_raw).hexdigest() != pointer.get('manifest_sha256'):
        raise ValueError('cost generation manifest hash differs')
    review = _json(review_raw)
    predecessor = review.get('predecessor', {})
    if (review.get('window_sha256') != generation
            or predecessor.get('window_sha256') != generation
            or _digest(predecessor.get('identity')) != generation):
        raise ValueError('cost generation review binding differs')
    if (folder / 'predecessor').is_symlink():
        raise ValueError('cost archive must be a local directory')
    for name, digest in review.get('archived_sha256', {}).items():
        if name not in {'snapshot', 'budget', 'receipt', 'rotation', 'report'}:
            raise ValueError('invalid archive member')
        raw = _bytes(folder / 'predecessor' / (name + '.json'), required=True)
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('cost generation archive hash differs')
    if 'snapshot' in review.get('archived_sha256', {}) and _bytes(folder / 'state.json') is None:
        raise ValueError('successor snapshot ledger is missing')
    return folder / 'state.json'


def window(root):
    """Immutable window identity excludes heartbeat/status timestamps."""
    from .cost_sampling import TARGET
    root = Path(root)
    state = state_path(root)
    history = _json(_bytes(state.with_suffix('.budget.json'), required=True))
    samples = history.get('distinct_samples')
    if not isinstance(samples, list) or len(samples) != TARGET or history.get('review_due') is not True:
        raise ValueError('no complete review-due window')
    shapes, attempts = set(), set()
    for sample in samples:
        if not isinstance(sample, dict):
            raise ValueError('invalid review sample')
        for key in ('run', 'items', 'records', 'body_bytes'):
            if type(sample.get(key)) is not int or sample[key] < 0:
                raise ValueError('invalid review dimension')
        stamp = sample.get('attempted_at')
        if type(stamp) not in (int, float) or not math.isfinite(stamp) or stamp <= 0 or stamp in attempts:
            raise ValueError('invalid or repeated review attempt')
        attempts.add(stamp)
        shapes.add(tuple(sample[k] for k in ('items', 'records', 'body_bytes')))
    if len(shapes) != TARGET:
        raise ValueError('review population is not distinct')
    if type(history.get('runs')) is not int or history['runs'] < max(s['run'] for s in samples):
        raise ValueError('review run coverage is inconsistent')
    rotation = _json(_bytes(root / 'cost-active-rotation.json', required=True))
    sources = [s for s in rotation.get('samples', []) if isinstance(s, dict) and s.get('attempted_at') in attempts]
    if len(sources) != TARGET or {s['attempted_at'] for s in sources} != attempts:
        raise ValueError('review source coverage is incomplete or duplicated')
    by_stamp = {s['attempted_at']: s for s in sources}
    for sample in samples:
        entry = by_stamp[sample['attempted_at']]
        if any(entry.get(k) != v for k, v in sample.items()):
            raise ValueError('source and budget sample differ')
        source = entry.get('source')
        if not isinstance(source, dict) or any(not isinstance(source.get(k), str) or not source[k] for k in ('agent', 'harness', 'session', 'path')):
            raise ValueError('review source identity is incomplete')
    receipt = _json(_bytes(state.with_suffix('.receipt.json'), required=True))
    cooldown = receipt.get('next_request_after')
    if cooldown is not None and (type(cooldown) not in (int, float) or not math.isfinite(cooldown) or cooldown < 0):
        raise ValueError('invalid request cooldown')
    snapshot = _bytes(state)
    if snapshot is not None:
        _json(snapshot)
    identity = {'schema_version': 1, 'state': str(state.relative_to(root)),
                'limits': LIMITS, 'history': history,
                'sources': sorted(sources, key=lambda s: s['attempted_at']),
                'snapshot_sha256': hashlib.sha256(snapshot).hexdigest() if snapshot is not None else None,
                'next_request_after': receipt.get('next_request_after')}
    return {'window_sha256': _digest(identity), 'identity': identity}


def _write(path, raw):
    # A failed preparation stays on disk for inspection, never overwritten.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as target:
        target.write(raw)
        target.flush()
        os.fsync(target.fileno())


def describe(root):
    state = state_path(root)
    history = _json(_bytes(state.with_suffix('.budget.json'), required=True))
    if history.get('review_due') is True:
        return {'status': 'REVIEW_DUE', **window(root)}
    return {'status': 'SAMPLING', 'state': str(state.relative_to(root)),
            'lifetime_runs': history.get('runs'),
            'window_samples': len(history.get('distinct_samples', [])),
            'accepted_review': history.get('accepted_review'),
            'publication': 'not established by review status'}


def _sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def advance(root, expected, decision, *, execute=False):
    """Caller holds cost.lock. Decision is evidence, not a credential/role grant."""
    root = Path(root)
    current = window(root)
    if expected != current['window_sha256']:
        raise ValueError('review window hash mismatch; read current evidence')
    if (set(decision) != {'schema_version', 'window_sha256', 'decision', 'mode', 'reviewer', 'evidence_ref'}
            or type(decision.get('schema_version')) is not int or decision['schema_version'] != 1
            or decision.get('window_sha256') != expected
            or decision.get('decision') != 'accept' or decision.get('mode') not in {'bounded-pilot', 'bounded-continuous'}
            or any(not isinstance(decision.get(k), str) or not decision[k].strip() for k in ('reviewer', 'evidence_ref'))):
        raise ValueError('decision must bind this accepted bounded policy window and ruling')
    state = state_path(root)
    for path in (root / 'cost-graph-state.json', root / LEGACY, state):
        if path.with_suffix('.pending.json').exists() or path.with_suffix('.pending.json').is_symlink():
            raise ValueError('pending cost write requires reconciliation')
    parent = root / GENERATIONS
    folder = parent / expected
    if parent.is_symlink() or folder.exists() or folder.is_symlink():
        raise ValueError('pre-existing generation requires readback, never overwrite')
    result = {'status': 'READY', 'window_sha256': expected, 'mode': decision['mode'],
              'successor': str((folder / 'state.json').relative_to(root)), 'published': False}
    if not execute:
        return result
    parent.mkdir(mode=0o700, exist_ok=True)
    folder.mkdir(mode=0o700)
    archive = folder / 'predecessor'
    archive.mkdir(mode=0o700)
    copied = {}
    for name, path in [('snapshot', state), ('budget', state.with_suffix('.budget.json')),
                       ('receipt', state.with_suffix('.receipt.json')),
                       ('rotation', root / 'cost-active-rotation.json'), ('report', root / 'cost-active-review.json')]:
        raw = _bytes(path)
        if raw is not None:
            _write(archive / (name + '.json'), raw)
            copied[name] = hashlib.sha256(raw).hexdigest()
    _sync_dir(archive)
    history = copy.deepcopy(current['identity']['history'])
    # A NEW generation, not erasure of the predecessor or lifetime accounting.
    history.update(samples=[], distinct_samples=[], distinct_shapes=0,
                   distinct_shapes_saturated=False, review_due=False,
                   review_window_started_at=time.time(),
                   accepted_review_archive=str(archive.relative_to(root)),
                   accepted_review={'window_sha256': expected, **decision})
    _write(folder / 'state.budget.json', _canonical(history))
    raw = _bytes(archive / 'snapshot.json')
    if raw is not None:
        _write(folder / 'state.json', raw)
    receipt = _json(_bytes(archive / 'receipt.json', required=True))
    receipt.update(status='UNKNOWN', detail='new review generation; no new publication', requests=0)
    _write(folder / 'state.receipt.json', _canonical(receipt))
    review_raw = _canonical({'window_sha256': expected, 'decision': decision,
                             'predecessor': current, 'archived_sha256': copied})
    _write(folder / 'review.json', review_raw)
    _sync_dir(folder)
    _sync_dir(parent)
    if window(root)['window_sha256'] != expected:
        raise ValueError('evidence changed during preparation; preserve generation for inspection')
    fd, temporary = tempfile.mkstemp(prefix='.cost-generation-', dir=root)
    with os.fdopen(fd, 'wb') as pointer:
        os.fchmod(pointer.fileno(), 0o600)
        pointer.write(_canonical({'schema_version': 1, 'generation': expected,
                                 'manifest_sha256': hashlib.sha256(review_raw).hexdigest()}))
        pointer.flush()
        os.fsync(pointer.fileno())
    os.replace(temporary, root / POINTER)
    _sync_dir(root)
    if state_path(root) != folder / 'state.json':
        raise ValueError('generation readback differs; preserve outcome uncertainty')
    return {**result, 'status': 'ADVANCED', 'published': False}


def rollover(root):
    """Caller holds cost.lock; only a hash-bound continuous ruling can roll.

    This applies the original policy, not a new human acceptance. The original
    decision and every completed population stay in predecessor archives.
    Camayoc still enforces the hard per-publication envelope before networking.
    A refused/out-of-envelope observation needs a new explicit review instead.
    """
    root = Path(root)
    state = state_path(root)
    if state == root / LEGACY:
        return False
    manifest = _json(_bytes(state.parent / 'review.json', required=True))
    policy = manifest.get('decision', {})
    if policy.get('mode') != 'bounded-continuous':
        return False
    # The selected manifest is bound by the pointer hash. Do not accept a
    # mutable budget's accepted_review as policy authority.
    if (manifest.get('predecessor', {}).get('identity', {}).get('limits') != LIMITS
            or set(policy) != {'schema_version', 'window_sha256', 'decision',
                               'mode', 'reviewer', 'evidence_ref'}
            or policy.get('schema_version') != 1 or policy.get('decision') != 'accept'
            or any(not isinstance(policy.get(k), str) or not policy[k].strip()
                   for k in ('reviewer', 'evidence_ref'))):
        raise ValueError('continuous policy binding differs; review required')
    current = window(root)
    for sample in current['identity']['history']['distinct_samples']:
        if any(sample[key] > LIMITS[key] for key in ('items', 'records', 'body_bytes')):
            return False
    inherited = {**policy, 'window_sha256': current['window_sha256']}
    advance(root, current['window_sha256'], inherited, execute=True)
    return True


def run(args):
    """Explicit local review operation. Never runs the counting/publish path."""
    root = Path(args.root)
    try:
        if args.bead or args.sync:
            raise ValueError('review cannot be combined with cost reads or sync')
        config = _json(_bytes(root / 'cost.json', required=True))
        if config.get('sample_active_sources') is not True:
            raise ValueError('review is only for the active sampler')
        # Share the normal producer lock; never replace it or steal a busy lock.
        fd = os.open(root / 'cost.lock', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'r') as lock:
            if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode):
                raise ValueError('cost lock must be a regular file')
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.accept_window:
                if not args.decision_file:
                    raise ValueError('acceptance requires a decision file')
                decision = _json(_bytes(Path(args.decision_file), required=True))
                result = advance(root, args.accept_window, decision, execute=args.execute)
            else:
                if args.decision_file or args.execute:
                    raise ValueError('decision/execute require an exact acceptance hash')
                result = describe(root)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'cost review: UNKNOWN: {exc}')
        return 2
