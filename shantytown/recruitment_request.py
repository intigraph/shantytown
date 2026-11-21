"""Offline signed-request qualification for the existing controller.

No transport, privileged call or launcher is exposed here. Production binding
loading, controller integration and activation remain separate reviewed work.
The verifier key is a controller input; the request cannot nominate a key.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from types import SimpleNamespace

from .actor_identity import IdentityError
from .recruiter import check_binding

SCHEMA = 'shantytown.recruitment-request/v1'
DOMAIN = b'shantytown.recruitment-request/v1\x00'
FIELDS = {'schema', 'principal', 'uid', 'host', 'verb', 'job', 'item', 'repo',
          'pr', 'head', 'target', 'nonce', 'issued_at', 'expires_at'}


@dataclass(frozen=True)
class Binding:
    """Qualification input, never proof that a protected binding is installed."""
    principal: str
    uid: int
    host: str
    repos: tuple[str, ...]
    public_key: bytes


def message(body):
    if not isinstance(body, dict) or set(body) != FIELDS:
        raise IdentityError('invalid signed recruitment schema')
    try:
        raw = json.dumps(body, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=True, allow_nan=False).encode('ascii')
    except (ValueError, TypeError) as error:
        raise IdentityError('invalid signed recruitment encoding') from error
    if len(raw) > 4096:
        raise IdentityError('signed recruitment request exceeds bound')
    return DOMAIN + raw


def qualify(envelope, *, binding, now, ledger, native_binding):
    """Verify a data-only request and reserve its nonce, without executing it.

    native_binding is the existing exact-item controller lookup, not event or
    PR prose. Each authenticated attempt consumes its nonce even on a custody
    refusal. A crash after reservation never makes the request replayable.
    No key path, argv, environment or controller path is accepted on the wire.
    """
    reason = 'malformed'
    nonce = None
    try:
        if not isinstance(envelope, dict) or set(envelope) != {'body', 'signature'}:
            raise IdentityError('invalid signed recruitment envelope')
        body = envelope['body']
        raw = message(body)
        signature = envelope['signature']
        if (not isinstance(signature, str) or not re.fullmatch('[0-9a-f]{128}', signature)
                or not isinstance(binding.public_key, bytes) or len(binding.public_key) != 32):
            raise IdentityError('invalid recruitment signature representation')
        reason = 'signature'
        # The production controller must supply the root-bound enrolled key.
        # Never fall back to the diagnostic-only gate_verdict verifier.
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            from cryptography.exceptions import InvalidSignature
        except ImportError as error:
            raise IdentityError('recruitment signature verifier unavailable') from error
        try:
            Ed25519PublicKey.from_public_bytes(binding.public_key).verify(bytes.fromhex(signature), raw)
        except (ValueError, InvalidSignature) as error:
            raise IdentityError('recruitment signature refused') from error
        reason = 'scope'
        if (body['schema'] != SCHEMA or body['principal'] != binding.principal
                or not isinstance(body['principal'], str) or not body['principal']
                or type(body['uid']) is not int or type(binding.uid) is not int
                or body['uid'] != binding.uid or binding.uid < 10000
                or body['host'] != binding.host or not isinstance(binding.host, str) or not binding.host
                or body['verb'] not in ('launch', 'stop') or body['job'] != 'review'
                or not isinstance(body['repo'], str) or body['repo'] not in binding.repos
                or not re.fullmatch(r'intigraph/[A-Za-z0-9_][A-Za-z0-9_.-]*', body['repo'])
                or type(body['pr']) is not int or body['pr'] < 1
                or not isinstance(body['item'], str)
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', body['item'])
                or not isinstance(body['head'], str) or not re.fullmatch('[0-9a-f]{40}', body['head'])
                or (body['verb'] == 'launch' and body['target'] is not None)
                or (body['verb'] == 'stop' and (not isinstance(body['target'], str)
                    or not re.fullmatch('eph-review-[0-9a-f]{6}', body['target'])))):
            raise IdentityError('signed recruitment request outside scope')
        reason = 'expiry'
        if (type(now) is not int or type(body['issued_at']) is not int
                or type(body['expires_at']) is not int
                or not body['issued_at'] <= now < body['expires_at']
                or not 0 < body['expires_at'] - body['issued_at'] <= 120):
            raise IdentityError('signed recruitment expiry refused')
        reason = 'nonce'
        if not isinstance(body['nonce'], str) or not re.fullmatch('[0-9a-f]{64}', body['nonce']):
            raise IdentityError('invalid recruitment nonce')
        nonce = body['nonce']
        ledger.reserve(binding.principal, nonce)
        reason = 'custody'
        req = SimpleNamespace(**{key: body[key] for key in ('job', 'item', 'repo', 'pr', 'head')})
        check_binding(req, native_binding(body['item']))
        ledger.record(nonce, 'qualified', 'offline-only')
        return dict(body)
    except Exception:
        # Refusal reasons are fixed labels, never caller text or key material.
        ledger.record(nonce, 'refused', reason)
        raise


class Ledger:
    """Private controller-owned qualification state; no pruning or auto-retry."""
    def __init__(self, path):
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS nonces (principal TEXT, nonce TEXT, PRIMARY KEY(principal, nonce))')
        self.db.execute('CREATE TABLE IF NOT EXISTS audit (nonce TEXT, outcome TEXT, reason TEXT)')

    def reserve(self, principal, nonce):
        try:
            self.db.execute('INSERT INTO nonces VALUES (?, ?)', (principal, nonce))
        except sqlite3.IntegrityError as error:
            raise IdentityError('recruitment replay refused') from error

    def record(self, nonce, outcome, reason):
        self.db.execute('INSERT INTO audit VALUES (?, ?, ?)', (nonce, outcome, reason))

    def close(self):
        self.db.close()
