"""Source entrypoint from verified recruitment wakes to the pinned controller.

No listener, daemon, installer, sudo, administrator identity or retry is added.
The caller supplies its ordinary native tracker/forge/verdict adapters and an
operator-selected PR-to-item routing map. That map is only a lookup hint: the
existing work-request record must independently bind every exact PR/head.
Use these callbacks only inside the verified inbox's durable attempt boundary.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import time
from types import MappingProxyType

from .actor_identity import IdentityError
from . import ephemeral, gate_verdict, recruit_endpoint, recruit_request, recruiter
from .recruit_store import _directory
from .work_item import exact


def _caller_uid():
    return os.geteuid()


def sign_request(body, pin, path):
    """Read one private, pinned seed using directory FDs; never copy its value."""
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise IdentityError('recruiter private path refused')
    directory = _directory(path.parent, pin.uid)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                     dir_fd=directory)
        try:
            meta = os.fstat(fd)
            if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != pin.uid
                    or stat.S_IMODE(meta.st_mode) != 0o400 or meta.st_nlink != 1
                    or meta.st_size != 64):
                raise IdentityError('recruiter private custody refused')
            raw = os.read(fd, 65)
        finally:
            os.close(fd)
    finally:
        os.close(directory)
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        seed = bytes.fromhex(raw.decode('ascii'))
        if len(raw) != 64 or len(seed) != 32:
            raise ValueError
        key = Ed25519PrivateKey.from_private_bytes(seed)
        if key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw) != pin.public_key:
            raise ValueError
        return {'body': dict(body), 'signature': key.sign(recruit_request.message(body)).hex()}
    except (ImportError, ValueError, UnicodeError):
        raise IdentityError('recruiter private signing input unproved') from None


class ReviewAdapter:
    """Three callbacks for the existing verified inbox drain; review jobs only.

    ``candidate`` is the consumer's data class (e.g. Camayoc Candidate), not a
    command. ``items`` is trusted configuration, never PR/body/event custody.
    The native tracker exact-ID read and work-request parser remain the only
    custody source. Activation OFF refuses before policy, remote or key reads.
    """
    def __init__(self, *, root, host, policy, tracker, items, candidate, gh, quipu,
                 private_key, clock=time.time):
        if not isinstance(items, dict) or not 1 <= len(items) <= 256:
            raise IdentityError('bounded configured item routing required')
        for key, value in items.items():
            if (not isinstance(key, tuple) or len(key) != 2
                    or not isinstance(key[0], str)
                    or not re.fullmatch(r'intigraph/[A-Za-z0-9_.-]+', key[0])
                    or type(key[1]) is not int or key[1] < 1
                    or not isinstance(value, str)
                    or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]*', value)):
                raise IdentityError('configured item route refused')
        self.root, self.host, self.policy = Path(root), host, policy
        self.tracker, self.items = tracker, MappingProxyType(dict(items))
        self.candidate, self.gh, self.quipu = candidate, gh, quipu
        self.private_key, self.clock = Path(private_key), clock

    def _active(self):
        if self.policy.recruitment_launch_ready is not True:
            raise IdentityError('recruiter adapter activation is gated')

    def _request(self, value):
        return ephemeral.Request(job=value.job, item=value.item, repo=value.repo,
                                 pr=value.pr, head=value.head)

    def _scope(self, request):
        self._active()
        scope = recruiter.load(root=self.root, host=self.host)
        pin = recruit_request.load_controller_binding()
        if (scope is None or scope.uid != _caller_uid() or pin.uid != scope.uid
                or pin.principal != scope.principal or pin.host != self.host
                or pin.root != str(self.root.resolve()) or request.repo not in pin.repos):
            raise IdentityError('requester and protected controller binding differ')
        scope.check(request, root=self.root, host=self.host)
        if self.items.get((request.repo, request.pr)) != request.item:
            raise IdentityError('candidate differs from configured native item route')
        return pin

    def native_binding(self, item):
        found = exact(self.tracker, item)
        return gate_verdict.work_request(getattr(found, 'description', None))

    def admit(self, value):
        request = self._request(value)
        self._scope(request)
        recruiter.cli_admit(request, policy=self.policy, gh=self.gh, quipu=self.quipu,
                            binding=self.native_binding)

    def resolve_ready(self, event, payload):
        self._active()
        if not isinstance(payload, dict):
            return None
        repository = payload.get('repository')
        if not isinstance(repository, dict):
            return None
        repo = repository.get('full_name')
        if event in ('pull_request', 'pull_request_review'):
            subject = payload.get('pull_request')
            if not isinstance(subject, dict) or not isinstance(subject.get('head'), dict):
                return None
            pr, head = subject.get('number'), subject['head'].get('sha')
        elif event in ('check_run', 'check_suite', 'workflow_run'):
            subject = payload.get(event)
            if not isinstance(subject, dict):
                return None
            pulls = subject.get('pull_requests')
            if not isinstance(pulls, list) or len(pulls) != 1 or not isinstance(pulls[0], dict):
                return None
            pr, head = pulls[0].get('number'), subject.get('head_sha')
        else:
            return None
        if (not isinstance(repo, str) or type(pr) is not int
                or not isinstance(head, str) or not re.fullmatch('[0-9a-f]{40}', head)):
            return None
        item = self.items.get((repo, pr))
        if item is None:
            return None
        value = self.candidate(repo=repo, pr=pr, head=head, job='review', item=item)
        self.admit(value)
        return value

    def spawn(self, value):
        request = self._request(value)
        pin = self._scope(request)
        # A routing hint and earlier readiness are never a signing lease.
        recruiter.check_binding(request, self.native_binding(request.item))
        now = self.clock()
        if type(now) not in (int, float) or not math.isfinite(now):
            raise IdentityError('recruiter clock unproved')
        body = dict(schema=recruit_request.SCHEMA, principal=pin.principal, uid=pin.uid,
                    host=pin.host, verb='launch', job='review', item=request.item,
                    repo=request.repo, pr=request.pr, head=request.head, target=None,
                    nonce=secrets.token_hex(32), issued_at=int(now), expires_at=int(now)+60)
        envelope = sign_request(body, pin, self.private_key)
        if self._scope(request) != pin:
            raise IdentityError('requester binding changed before signed handoff')
        receipt = recruit_endpoint.exchange(envelope, policy=self.policy)
        if (not isinstance(receipt, dict)
                or set(receipt) != {'state', 'operation', 'name', 'head', 'live'}
                or receipt['state'] != 'launched' or receipt['live'] is not True
                or receipt['operation'] != hashlib.sha256(recruit_request.message(body)).hexdigest()
                or receipt['head'] != request.head or not isinstance(receipt['name'], str)
                or not re.fullmatch('eph-review-[0-9a-f]{6}', receipt['name'])):
            # The send may already have spent its nonce. Never retry or accept
            # prepared/refused/mismatched output as a confirmed spawned job.
            raise IdentityError('controller launch receipt unproved; retain attempt')
        return json.dumps(receipt, sort_keys=True, separators=(',', ':'))
