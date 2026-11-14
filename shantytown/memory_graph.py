"""ST file records over ordinary Quipu query/update, with one-graph atomic CAS.

No server memory API or new vocabulary: Artifact records retain immutable JSON
manifests and exact intents, and ordinary RDF links identify their parts/head.
The server's normal writer/shape/provenance policy remains authoritative.
"""
from __future__ import annotations

import hashlib
import json
import re

RDF = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
RDFS = 'http://www.w3.org/2000/01/rdf-schema#'
PROV = 'http://www.w3.org/ns/prov#'
PART = 'http://purl.org/dc/terms/hasPart'
MAX_FILES = 128


def literal(value):
    return json.dumps(value, ensure_ascii=True)


def iri(value):
    if (not isinstance(value, str) or not re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', value)
            or any(c.isspace() or ord(c) < 32 or c in '<>"{}|^`\\' for c in value)):
        from .memory_remote import Unproven
        raise Unproven('invalid graph identity')
    return '<' + value + '>'


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def digest(request):
    return hashlib.sha256(encoded(request).encode()).hexdigest()


class Graph:
    def __init__(self, client):
        self.client = client
        self.owner = client.owner
        key = digest(self.owner.wire())
        self.graph = 'urn:shantytown:crew-files:' + key
        self.collection = self.graph + ':collection'

    def rows(self, pattern, *, limit):
        from .memory_remote import Unproven
        query = f'SELECT * WHERE {{ {pattern} }} LIMIT {limit}'
        result = self.client._request('/query', {'query': query})
        if (not isinstance(result, dict) or result.get('truncated') is not False
                or not isinstance(result.get('rows'), list)
                or type(result.get('count')) is not int
                or result['count'] != len(result['rows']) or len(result['rows']) >= limit
                or 'error' in result):
            raise Unproven('ordinary graph coverage unproven')
        if any(not isinstance(row, dict) for row in result['rows']):
            raise Unproven('ordinary graph row invalid')
        return result['rows']

    def read_record(self, subject):
        from .memory_remote import Unproven, _json
        rows = self.rows(f'GRAPH {iri(self.graph)} {{ {iri(subject)} '
                         f'{iri(RDFS + "comment")} ?payload }}', limit=2)
        if not rows:
            return None
        if set(rows[0]) != {'payload'} or not isinstance(rows[0]['payload'], str):
            raise Unproven('ordinary graph record malformed')
        return _json(rows[0]['payload'])

    def export(self):
        from .memory_remote import Unproven, _export_files
        rows = self.rows(f'GRAPH {iri(self.graph)} {{ {iri(self.collection)} '
                         f'{iri(RDFS + "seeAlso")} ?head }}', limit=3)
        empty = dict(format='shantytown.memory-files/v1', coverage='this_repository_owner_records',
                     snapshot=None, files=[])
        if not rows:
            return empty
        if len(rows) != 1 or set(rows[0]) != {'head'}:
            raise Unproven('ordinary graph has ambiguous head')
        head = rows[0]['head']
        manifest = self.read_record(head)
        if (not isinstance(manifest, dict) or manifest.get('owner') != self.owner.wire()
                or manifest.get('revision') != head or not isinstance(manifest.get('files'), dict)
                or len(manifest['files']) > MAX_FILES):
            raise Unproven('ordinary graph manifest invalid')
        rows = self.rows(f'GRAPH {iri(self.graph)} {{ {iri(head)} {iri(PART)} ?revision . '
                         f'?revision {iri(RDFS + "comment")} ?payload }}', limit=MAX_FILES + 1)
        from .memory_remote import _json, canonical_intent
        records = []
        for row in rows:
            if set(row) != {'revision', 'payload'} or not isinstance(row['payload'], str):
                raise Unproven('ordinary graph file row invalid')
            record = _json(row['payload'])
            if not isinstance(record, dict):
                raise Unproven('ordinary graph revision malformed')
            request = canonical_intent(record.get('intent'), self.owner)
            receipt = self.client._receipt({'receipt': record.get('receipt')}, request)
            if receipt['file']['revision'] != row['revision']:
                raise Unproven('ordinary graph revision identity differs')
            records.append(dict(owner=self.owner.wire(), path=request['path'], text=request['text'],
                revision=row['revision'], harness=request['harness'], account=request['account'],
                committed_at=receipt.get('committed_at', 'UNKNOWN')))
        result = dict(empty, snapshot=manifest, files=records)
        _export_files(result, self.owner)
        return result

    def marker(self, request):
        key = digest(dict(owner=self.owner.wire(), key=request['idempotency_key']))
        return self.graph + ':intent:' + key

    def receipt(self, request):
        from .memory_remote import Unproven
        rows = self.rows(f'GRAPH {iri(self.graph)} {{ {iri(self.marker(request))} '
                         f'{iri(RDFS + "seeAlso")} ?revision }}', limit=3)
        if not rows:
            return None
        expected = 'urn:quipu:memory:revision:' + digest(request)
        if len(rows) != 1 or rows[0] != {'revision': expected}:
            raise Unproven('ordinary graph idempotency conflict')
        record = self.read_record(expected)
        if not isinstance(record, dict) or record.get('intent') != request:
            raise Unproven('ordinary graph intent readback differs')
        return self.client._receipt({'receipt': record.get('receipt')}, request)

    def commit(self, request):
        from .memory_remote import Unproven
        # Replay precedes the now-stale head check; a lost reply is never a new intent.
        previous = self.receipt(request)
        if previous is not None:
            return previous
        envelope = self.export()
        baseline = envelope['snapshot']
        current = baseline['revision'] if baseline else None
        heads = dict(baseline['files']) if baseline else {}
        if (request['expected_snapshot'] != current or request['expected_file'] !=
                heads.get(request['path'], {}).get('revision')):
            raise Unproven('memory revision conflict; preserve local and remote')
        sha = digest(request)
        revision = 'urn:quipu:memory:revision:' + sha
        head = 'urn:quipu:memory:snapshot:' + sha
        data = b'' if request['text'] is None else request['text'].encode()
        file = dict(revision=revision, sha256=hashlib.sha256(data).hexdigest(),
                    bytes=len(data), tombstone=request['text'] is None)
        receipt = dict(owner=self.owner.wire(), path=request['path'], request_hash=sha,
                       snapshot=head, file=file)
        heads[request['path']] = file
        if len(heads) > MAX_FILES:
            raise Unproven('ordinary graph manifest exceeds bound')
        manifest = dict(owner=self.owner.wire(), revision=head, files=heads)
        from .quipu import resolve_onto, DEFAULT_ONTO
        root = self.client._credential_selection[0]
        onto = resolve_onto(root=root)
        if onto == DEFAULT_ONTO:
            raise Unproven('ordinary graph shape namespace unconfigured')
        def artifact(subject, value):
            return (f'{iri(subject)} {iri(RDF)} {iri(onto + "Artifact")} ; '
                f'{iri(RDFS + "label")} "ST crew file record" ; '
                f'{iri(onto + "reference")} {literal(subject)} ; '
                f'{iri(PROV + "wasAttributedTo")} {iri(self.owner.crew)} ; '
                f'{iri(PROV + "hadPrimarySource")} {iri(self.owner.project)} ; '
                f'{iri(RDFS + "comment")} {literal(encoded(value))} . ')
        triples = artifact(head, manifest) + artifact(revision, dict(intent=request, receipt=receipt))
        triples += f'{iri(self.collection)} {iri(RDFS + "seeAlso")} {iri(head)} . '
        for item in heads.values():
            triples += f'{iri(head)} {iri(PART)} {iri(item["revision"])} . '
        old = (f'{iri(self.collection)} {iri(RDFS + "seeAlso")} {iri(current)} . '
               if current else '')
        condition = (f'GRAPH {iri(self.graph)} {{ {old} }} ' if old else '')
        # The atomic WHERE repeats the precondition inside Quipu, independently
        # of our earlier manifest read. Keep all histories; retract only the pointer.
        condition += (f'FILTER NOT EXISTS {{ GRAPH {iri(self.graph)} {{ '
            f'{iri(self.collection)} {iri(RDFS + "seeAlso")} ?other '
            + (f'FILTER(?other != {iri(current)}) ' if current else '') + '} } ')
        for subject in (self.marker(request), head, revision):
            condition += f'FILTER NOT EXISTS {{ GRAPH {iri(self.graph)} {{ {iri(subject)} ?p ?o }} }} '
        triples += f'{iri(self.marker(request))} {iri(RDFS + "seeAlso")} {iri(revision)} . '
        update = (f'DELETE {{ GRAPH {iri(self.graph)} {{ {old} }} }} '
                  f'INSERT {{ GRAPH {iri(self.graph)} {{ {triples} }} }} WHERE {{ {condition} }}')
        result = self.client._request('/update', {'update': update, 'actor': self.owner.crew,
            'source': 'shantytown-crew-files:' + sha}, identity=True)
        if (not isinstance(result, dict) or type(result.get('tx')) is not int
                or type(result.get('asserted')) is not int or result['asserted'] <= 0
                or type(result.get('retracted')) is not int
                or result['retracted'] != bool(current) or 'error' in result
                or result.get('conforms') is False
                or not isinstance(result.get('graphs'), list) or len(result['graphs']) != 1
                or not isinstance(result['graphs'][0], dict)
                or result['graphs'][0].get('graph') != self.graph
                or result['graphs'][0].get('tx') != result['tx']):
            raise Unproven('ordinary graph update unproven or CAS refused; retain intent')
        accepted = self.receipt(request)
        if accepted != receipt:
            raise Unproven('ordinary graph commit readback differs; retain intent')
        return accepted
