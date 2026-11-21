"""Signed input into the existing controller's admission path; no execution.

The source-only CLI is an explicit preview, not a transport listener. It cannot
return a launch/stop capability, and never calls the privileged launcher. Live
handoff, protected persistent state and activation remain separately gated.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
import select
import socket
import stat
import sys
import time

from .actor_identity import IdentityError
from . import ephemeral, recruit_request, recruiter

MAX_BYTES = 8192


def parse(raw):
    """Reject ambiguous JSON before either signature or custody processing."""
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_BYTES:
        raise IdentityError('controller request input exceeds bound or is empty')
    def unique(pairs):
        row = {}
        for key, value in pairs:
            if key in row:
                raise IdentityError('duplicate controller request field')
            row[key] = value
        return row
    try:
        return json.loads(raw, object_pairs_hook=unique)
    except (ValueError, UnicodeError) as error:
        raise IdentityError('controller request JSON refused') from error


def read_input():
    """One bounded stdin frame, ending at EOF; never wait forever for a pipe."""
    fd = sys.stdin.buffer.fileno()
    meta = os.fstat(fd)
    if stat.S_ISREG(meta.st_mode):
        return parse(os.read(fd, MAX_BYTES + 1))
    if not stat.S_ISFIFO(meta.st_mode):
        raise IdentityError('controller request requires a file or closed-frame pipe')
    deadline = time.monotonic() + 5
    raw = bytearray()
    while len(raw) <= MAX_BYTES:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([fd], [], [], remaining)[0]:
            raise IdentityError('controller request input timed out')
        chunk = os.read(fd, min(4096, MAX_BYTES + 1 - len(raw)))
        if not chunk:
            return parse(bytes(raw))
        raw.extend(chunk)
    raise IdentityError('controller request input exceeds bound')


def controller_authority(*, policy, actor, inside, role_of):
    # A signed recruiter payload does not make the process a controller. Keep
    # the existing verified administrator boundary; never use recruiter_scope
    # to grant the receiving process administrator authority.
    if not policy.require_verified_identity or inside:
        raise IdentityError('verified independent controller identity required')
    ephemeral.authority(actor, role_of, require_verified=True)


def stop_target(body, record):
    """A valid signer may stop only its own exact live review, never any UID."""
    expected = {key: body[key] for key in ('principal', 'uid', 'host', 'item', 'repo', 'pr', 'head')}
    expected['binding'] = 'chaski.github.work-request/v1'
    if (not isinstance(record, dict) or record.get('name') != body['target']
            or record.get('job') != 'review'
            or record.get('state') not in (ephemeral.LAUNCHING, ephemeral.LIVE)
            or record.get('recruiter') != expected
            or any(record.get(key) != body[key] for key in ('item', 'repo', 'pr', 'head', 'host'))
            or not isinstance(record.get('uid_binding'), dict)
            or type(record['uid_binding'].get('uid')) is not int
            or record['uid_binding']['uid'] < 10000
            or record['uid_binding']['uid'] in (body['uid'], os.geteuid())
            or not isinstance(record['uid_binding'].get('sha256'), str)
            or not re.fullmatch('[0-9a-f]{64}', record['uid_binding']['sha256'])):
        raise IdentityError('controller stop target ownership unproved')


def admitted_body(envelope, *, policy, actor, inside, role_of, root, host, ledger,
            native_binding, admit, clock=time.time):
    """Return the verified body copy after fresh admission, never caller state.

    The caller supplies controller-owned state. A preview uses memory; the
    separately gated handoff uses its private durable store. No execution occurs.
    """
    controller_authority(policy=policy, actor=actor, inside=inside, role_of=role_of)
    pin = recruit_request.load_controller_binding()
    if (pin.root != str(Path(root).resolve()) or pin.host != host
            or host != socket.gethostname() or pin.uid == os.geteuid()
            or pin.principal == actor):
        raise IdentityError('controller root/host/identity differs from protected binding')
    body = recruit_request.qualify(envelope, binding=pin, now=int(clock()), ledger=ledger,
                                   native_binding=native_binding)
    reason = 'admission'
    try:
        request = ephemeral.Request(job='review', item=body['item'], repo=body['repo'],
                                    pr=body['pr'], head=body['head'])
        if body['verb'] == 'launch':
            # This calls the same fresh forge/check/verdict/custody adapter as
            # scoped spawn. Event bytes or a prior receiver decision are no lease.
            admit(request)
        else:
            reason = 'target'
            stop_target(body, ephemeral.read(root, body['target']))
        reason = 'expiry'
        now = int(clock())
        if not body['issued_at'] <= now < body['expires_at']:
            raise IdentityError('controller request expired during admission')
        reason = 'custody'
        recruiter.check_binding(request, native_binding(request.item))
        # Recheck after the final native read too: a slow read cannot extend
        # the signed lease, even for a preview.
        if not body['issued_at'] <= int(clock()) < body['expires_at']:
            reason = 'expiry'
            raise IdentityError('controller request expired during custody read')
        ledger.record(body['nonce'], 'qualified', 'controller-admitted')
        return body
    except Exception:
        ledger.record(body['nonce'], 'refused', reason)
        raise



def receive(envelope, *, policy, actor, inside, role_of, root, host, ledger,
            native_binding, admit, clock=time.time):
    """Existing non-executable preview; its receipt is never a launch lease."""
    body = admitted_body(envelope, policy=policy, actor=actor, inside=inside,
                         role_of=role_of, root=root, host=host, ledger=ledger,
                         native_binding=native_binding, admit=admit, clock=clock)
    return {'schema': 'shantytown.recruitment-controller-qualification/v1',
            'request_sha256': hashlib.sha256(recruit_request.message(body)).hexdigest(),
            'principal': body['principal'], 'host': body['host'], 'verb': body['verb'],
            'job': 'review', 'item': body['item'], 'repo': body['repo'],
            'pr': body['pr'], 'head': body['head'], 'target': body['target'],
            'live': False, 'execution': 'refused', 'durable_acceptance': False}


def cli_qualify(a, *, policy, actor, inside, host, role_of, gh, quipu, binding):
    """Existing controller CLI adapter, deliberately dry-run only at this stage."""
    try:
        # Refuse mixed selectors before stdin, root key reads or any remote call.
        if (not a.dry_run or getattr(a, 'recruiter', False)
                or any(getattr(a, key, None) is not None for key in
                       ('job', 'item', 'pr_repo', 'pr', 'head', 'checkout', 'harness', 'evidence', 'verdict'))):
            raise IdentityError('controller qualification requires only --recruitment-request --dry-run')
        controller_authority(policy=policy, actor=actor, inside=inside, role_of=role_of)
        envelope = read_input()
        ledger = recruit_request.Ledger(':memory:')
        try:
            receipt = receive(envelope, policy=policy, actor=actor, inside=inside,
                              role_of=role_of, root=a.root, host=host, ledger=ledger,
                              native_binding=binding,
                              admit=lambda request: recruiter.cli_admit(
                                  request, policy=policy, gh=gh, quipu=quipu, binding=binding))
        finally:
            ledger.close()
        print(json.dumps(receipt, sort_keys=True))
        return 0
    except Exception as error:
        # No request text, paths, signatures or raw adapter exceptions in output.
        print('  refused: controller recruitment qualification unproved (' +
              type(error).__name__ + ')', file=sys.stderr)
        return 1
