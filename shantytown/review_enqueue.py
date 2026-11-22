"""Controller custody for approved reviews, independent of job teardown.

This is a storage contract, not an enqueue capability. Nothing imports it from
the live report path yet. Native receipt compatibility and the shared service
admission gate must qualify before that handoff can be enabled.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys

from .actor_identity import IdentityError
from . import job_review
from .recruit_store import _directory

MAX_BYTES = 16384
MAX_INTENTS = 50000
_HASH = re.compile('[0-9a-f]{64}')
_FIELDS = {'authority', 'repo', 'pr', 'pr_node', 'head', 'reviewer', 'record', 'signer', 'graph'}


def _bytes(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise IdentityError('duplicate enqueue custody field')
        value[key] = item
    return value


def _candidate(value):
    if (not isinstance(value, dict) or set(value) != _FIELDS
            or any(not isinstance(v, str) or not v or len(v) > 2048
                   for k, v in value.items() if k != 'pr')
            or type(value['pr']) is not int or value['pr'] <= 0
            or not re.fullmatch(r'https://[a-z0-9][a-z0-9.-]*(?::[0-9]{1,5})?', value['authority'])
            or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', value['repo'])
            or not re.fullmatch('[0-9a-f]{40}', value['head'])):
        raise IdentityError('enqueue candidate identity refused')
    return hashlib.sha256(_bytes(value)).hexdigest()


def _checked(value, key):
    if (not isinstance(value, dict)
            or set(value) != {'version', 'id', 'candidate', 'state', 'attempt', 'receipt'}
            or type(value['version']) is not int or value['version'] != 1
            or value['id'] != key or _candidate(value['candidate']) != key
            or value['state'] not in ('pending', 'attempting', 'queued', 'refused', 'unknown')
            or (value['state'] == 'pending' and (value['attempt'] is not None or value['receipt'] is not None))
            or (value['state'] != 'pending' and
                (not isinstance(value['attempt'], str) or not _HASH.fullmatch(value['attempt'])))
            or (value['state'] == 'attempting' and value['receipt'] is not None)
            or (value['state'] in ('queued', 'refused', 'unknown') and
                (not isinstance(value['receipt'], str) or not value['receipt'] or len(value['receipt']) > 2048))):
        raise IdentityError('enqueue intent schema or identity unproved')
    return value


class Store:
    """One pre-provisioned private directory; no paths from a review message.

    The controller supplies its configured root. Directory FDs pin ancestry,
    flock serializes controllers, and replace+fsync makes each transition
    durable before returning. Capacity exhaustion retains every old intent.
    """
    def __init__(self, root):
        if not sys.platform.startswith('linux'):
            raise IdentityError('enqueue custody requires Linux directory FDs')
        self.directory = _directory(Path(root) / 'ephemeral' / 'review-enqueue', os.geteuid())

    def _file(self, fd):
        meta = os.fstat(fd)
        if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.geteuid()
                or stat.S_IMODE(meta.st_mode) != 0o600 or meta.st_nlink != 1
                or meta.st_size > MAX_BYTES):
            raise IdentityError('enqueue custody is not private single-link regular data')

    @contextmanager
    def _locked(self):
        fd = os.open('.intents.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW |
                     os.O_NONBLOCK | os.O_CLOEXEC, 0o600, dir_fd=self.directory)
        try:
            self._file(fd)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(fd)

    def _read(self, key):
        if not isinstance(key, str) or not _HASH.fullmatch(key):
            raise IdentityError('enqueue intent key refused')
        try:
            fd = os.open(key + '.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK |
                         os.O_CLOEXEC, dir_fd=self.directory)
        except FileNotFoundError:
            return None
        with os.fdopen(fd, 'rb') as stream:
            self._file(stream.fileno())
            raw = stream.read(MAX_BYTES + 1)
        try:
            value = json.loads(raw, object_pairs_hook=_unique)
        except (ValueError, UnicodeError) as error:
            raise IdentityError('enqueue custody JSON unproved') from error
        return _checked(value, key)

    def _write(self, value):
        raw = _bytes(_checked(value, value['id']))
        if len(raw) > MAX_BYTES:
            raise IdentityError('enqueue intent exceeds bound')
        name = '.prepared-' + secrets.token_hex(16)
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW |
                     os.O_CLOEXEC, 0o600, dir_fd=self.directory)
        # A crash leaves a private prepared file. It is evidence, never a reason
        # to silently repair state or repeat a possibly completed remote write.
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, value['id'] + '.json', src_dir_fd=self.directory, dst_dir_fd=self.directory)
        os.fsync(self.directory)
        return self._read(value['id'])

    def retain(self, authority, spec, message, *, quipu=None):
        """Verify the enrolled exact-head APPROVE before acquiring custody.

        A retained record is evidence of past verification, not a lease to
        enqueue: revocation, head, CI and service gates need fresh native checks.
        """
        if (type(spec.get('uid')) is not int or spec['uid'] == os.geteuid()
                or message.get('verdict') != 'approve'
                or not job_review.confirmed(spec, message, quipu=quipu)):
            raise IdentityError('enqueue needs an independently verified job APPROVE')
        policy, _ = job_review.policy(spec)
        candidate = {k: policy[k] for k in ('repo', 'pr', 'pr_node', 'head', 'signer', 'graph')}
        candidate.update(authority=authority, reviewer=spec['principal'], record=message['review']['record'])
        key = _candidate(candidate)
        with self._locked():
            old = self._read(key)
            if old is not None:
                return old
            entries = os.listdir(self.directory)
            if any(name != '.intents.lock' and not re.fullmatch('[0-9a-f]{64}\\.json', name)
                   for name in entries):
                raise IdentityError('unexpected enqueue custody entry; operator reconciliation required')
            if len(entries) - 1 >= MAX_INTENTS:
                raise IdentityError('enqueue custody capacity reached; retain state')
            return self._write(dict(version=1, id=key, candidate=candidate,
                                    state='pending', attempt=None, receipt=None))

    def read(self, key):
        with self._locked():
            return self._read(key)

    def begin(self, key):
        """Durably consume ONE attempt before any future native mutation.

        A crash in 'attempting' or an 'unknown' outcome never becomes pending
        automatically. Remote reconciliation is required outside this module.
        """
        with self._locked():
            value = self._read(key)
            if value is None or value['state'] != 'pending':
                raise IdentityError('enqueue attempt already consumed or unknown')
            value.update(state='attempting', attempt=secrets.token_hex(32))
            return self._write(value)

    def finish(self, key, attempt, state, receipt):
        if state not in ('queued', 'refused', 'unknown'):
            raise IdentityError('enqueue outcome refused')
        with self._locked():
            value = self._read(key)
            if value is None or value['state'] != 'attempting' or value['attempt'] != attempt:
                raise IdentityError('enqueue attempt identity or outcome unproved')
            value.update(state=state, receipt=receipt)
            return self._write(value)

    def close(self):
        if self.directory is not None:
            os.close(self.directory)
            self.directory = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
