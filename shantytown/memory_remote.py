"""Bounded Quipu file transport; native projection requires verified own identity.

Shared export is deliberately not an input to stage_own. Credentials use the
existing selector and stay in request headers. No redirects, retries, root
replacement, native settings changes, or automatic tombstones from scan gaps.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import hashlib
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from . import quipu_auth
from .memory_files import MemoryFile, UnsafeMemory, stage, validate

LIMIT = 8 * 1024 * 1024


class Unproven(UnsafeMemory):
    """No result is accepted and no automatic retry is authorized."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


@dataclass(frozen=True)
class Owner:
    deployment: str
    project: str
    crew: str

    def __post_init__(self):
        for value in self.wire().values():
            if (not isinstance(value, str) or not urlsplit(value).scheme
                    or any(c.isspace() for c in value)):
                raise Unproven('memory owner requires exact absolute identities')

    def wire(self):
        return dict(deployment=self.deployment, project=self.project, crew=self.crew)


def _json(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise Unproven('duplicate memory response field')
            value[key] = item
        return value
    try:
        return json.loads(raw, object_pairs_hook=unique)
    except (UnicodeError, ValueError) as error:
        raise Unproven('invalid memory response') from error


class Client:
    def __init__(self, server: str, owner: Owner, *, opener=None):
        parsed = urlsplit(server)
        if (parsed.scheme not in {'https', 'http'} or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in {'', '/'}):
            raise Unproven('invalid memory server origin')
        self.server = server.rstrip('/')
        self.owner = owner
        self.opener = opener or build_opener(_NoRedirect)

    @classmethod
    def for_agent(cls, root, agent, server, deployment, project, *, opener=None):
        # Reuse the administrator-owned credential mapping. A label, path or
        # URI concatenation cannot resolve a crew identity; missing mapping is
        # unsupported rather than a fallback to a shared credential's owner.
        from .crew_credentials import selection
        selected = selection(root, agent)
        if selected is None or 'quipu_cli' not in selected[1]:
            raise Unproven('named crew CLI credential selection unavailable')
        owner = Owner(deployment, project, selected[1]['principal'])
        return cls(server, owner, opener=opener)

    def _request(self, endpoint, body, *, identity=False):
        headers = {'Content-Type': 'application/json', 'X-Quipu-Client': 'crew-memory'}
        if identity:
            # A shared fallback is possible here; the SERVER must reject it for
            # own writes/projection. Local card names are not authentication.
            headers.update(quipu_auth.write_headers(self.server))
        encoded = json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode()
        if len(encoded) > 1024 * 1024:
            raise Unproven('memory request exceeds limit')
        request = Request(self.server + endpoint, data=encoded, headers=headers)
        try:
            with self.opener.open(request, timeout=10) as response:
                if response.status != 200:
                    raise Unproven('memory response not successful')
                raw = response.read(LIMIT + 1)
        except HTTPError as error:
            # Never include URLs, response bodies, source text or credentials.
            if error.code in {401, 403} and identity:
                raise quipu_auth.refuse(self.server, 'memory identity refused') from None
            if error.code == 409:
                raise Unproven('memory revision conflict; preserve local and remote') from None
            raise Unproven('memory HTTP refusal; no retry') from None
        except (URLError, TimeoutError, OSError):
            raise Unproven('memory outcome unknown; retain exact request for readback') from None
        if len(raw) > LIMIT:
            raise Unproven('memory response exceeds limit')
        return _json(raw)

    def read(self):
        result = self._request('/memory/read', self.owner.wire())
        if not isinstance(result, dict) or result.get('coverage') != 'this_repository_owner_records':
            raise Unproven('memory read coverage unproven')
        snapshot = result.get('snapshot')
        if snapshot is not None and (not isinstance(snapshot, dict)
                                     or snapshot.get('owner') != self.owner.wire()):
            raise Unproven('memory read owner mismatch')
        return snapshot

    def _receipt(self, result, request, *, absent=False):
        if not isinstance(result, dict) or 'receipt' not in result:
            raise Unproven('memory receipt response missing')
        receipt = result['receipt']
        if receipt is None and absent:
            return None
        intent = canonical_intent(request, self.owner)
        digest = hashlib.sha256(json.dumps(intent, ensure_ascii=False,
                                           separators=(',', ':')).encode()).hexdigest()
        text = intent['text']
        data = b'' if text is None else text.encode('utf-8')
        file = receipt.get('file') if isinstance(receipt, dict) else None
        if (not isinstance(receipt, dict) or receipt.get('owner') != self.owner.wire()
                or receipt.get('path') != intent['path'] or receipt.get('request_hash') != digest
                or receipt.get('snapshot') != 'urn:quipu:memory:snapshot:' + digest
                or not isinstance(file, dict)
                or file.get('revision') != 'urn:quipu:memory:revision:' + digest
                or file.get('sha256') != hashlib.sha256(data).hexdigest()
                or type(file.get('bytes')) is not int or file['bytes'] != len(data)
                or type(file.get('tombstone')) is not bool or file['tombstone'] != (text is None)):
            raise Unproven('memory commit receipt mismatch; preserve request')
        return receipt

    def commit(self, request):
        request = canonical_intent(request, self.owner)
        return self._receipt(self._request('/memory/commit', request, identity=True), request)

    def receipt(self, request):
        request = canonical_intent(request, self.owner)
        return self._receipt(self._request('/memory/receipt', request, identity=True),
                             request, absent=True)

    def export(self):
        """Intentional cross-crew read, never an own-projection credential."""
        envelope = self._request('/memory/export', self.owner.wire())
        _export_files(envelope, self.owner, allow_empty=True)
        return envelope

    def query(self, text, *, limit=20):
        """Bounded literal search of one declared owner's repository records."""
        if (not isinstance(text, str) or not text.strip() or len(text.encode()) > 4096
                or type(limit) is not int or not 1 <= limit <= 20):
            raise Unproven('memory query or result bound invalid')
        envelope = self.export()
        matches = []
        for record in envelope['files']:
            source = record.get('text')
            if not isinstance(source, str):
                continue
            if text.casefold() not in (record['path'] + '\n' + source).casefold():
                continue
            matches.append(dict(owner=self.owner.wire(), path=record['path'],
                revision=record['revision'], harness=record.get('harness', 'UNKNOWN'),
                account=record.get('account', 'UNKNOWN'),
                committed_at=record.get('committed_at', 'UNKNOWN'),
                excerpt=source[:1600], excerpt_truncated=len(source) > 1600,
                historical=True))
        return {'coverage': envelope['coverage'], 'owner': self.owner.wire(),
                'matches': matches[:limit], 'truncated': len(matches) > limit,
                'search': 'literal; selected owner only; not a global index'}

    def stage_own(self, parent: Path):
        result = self._request('/memory/projection', self.owner.wire(), identity=True)
        files = verified_files(result, self.owner)
        return stage(files, parent)


def canonical_intent(request, owner: Owner):
    fields = ('path', 'text', 'expected_snapshot', 'expected_file',
              'idempotency_key', 'harness', 'account')
    if (not isinstance(request, dict) or set(request) != {'owner', *fields}
            or request['owner'] != owner.wire()):
        raise Unproven('memory request owner or fields mismatch')
    for key in ('path', 'idempotency_key', 'harness', 'account'):
        if not isinstance(request[key], str):
            raise Unproven('memory request metadata invalid')
    for key in ('expected_snapshot', 'expected_file'):
        if request[key] is not None and not isinstance(request[key], str):
            raise Unproven('memory parent revision invalid')
    text = request['text']
    if text is not None and not isinstance(text, str):
        raise Unproven('memory source text invalid')
    MemoryFile(request['path'], b'' if text is None else text.encode('utf-8'))
    return dict(owner=owner.wire(), **{key: request[key] for key in fields})


def verified_files(result, owner: Owner):
    """Bind named owner, immutable manifest, revision metadata and source bytes."""
    if (not isinstance(result, dict) or result.get('authenticated_owner') != owner.crew
            or not isinstance(result.get('export'), dict)):
        raise Unproven('own memory projection identity unproven')
    return _export_files(result['export'], owner)


def _export_files(envelope, owner, *, allow_empty=False):
    if (not isinstance(envelope, dict) or envelope.get('format') != 'quipu.memory-files/v1'
            or envelope.get('coverage') != 'this_repository_owner_records'):
        raise Unproven('memory projection coverage unproven')
    snapshot, records = envelope.get('snapshot'), envelope.get('files')
    if allow_empty and snapshot is None and records == []:
        return ()
    if not isinstance(snapshot, dict) or snapshot.get('owner') != owner.wire():
        raise Unproven('memory snapshot missing or wrong owner')
    heads = snapshot.get('files')
    if not isinstance(heads, dict) or not isinstance(records, list) or len(heads) != len(records):
        raise Unproven('memory manifest coverage mismatch')
    files, seen = [], set()
    for record in records:
        if not isinstance(record, dict) or record.get('owner') != owner.wire():
            raise Unproven('memory revision owner mismatch')
        path = record.get('path')
        if not isinstance(path, str) or path in seen or path not in heads:
            raise Unproven('memory revision path mismatch')
        seen.add(path)
        head = heads[path]
        if (not isinstance(head, dict) or type(head.get('tombstone')) is not bool
                or not isinstance(head.get('revision'), str)
                or record.get('revision') != head['revision']):
            raise Unproven('memory file head invalid')
        text = record.get('text')
        if head['tombstone']:
            if text is not None:
                raise Unproven('memory tombstone has source text')
            continue
        if not isinstance(text, str):
            raise Unproven('memory source text missing')
        file = MemoryFile(path, text.encode('utf-8'))
        if head.get('sha256') != file.sha256 or head.get('bytes') != len(file.data):
            raise Unproven('memory source checksum mismatch')
        files.append(file)
    result = tuple(sorted(files, key=lambda file: file.path))
    validate(result)
    return result
