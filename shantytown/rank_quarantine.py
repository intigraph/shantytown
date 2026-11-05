"""Archive Jev answer artifacts in a proven low-trust graph; never promote them."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import stat
from urllib.request import Request, urlopen

from .board_rank import IRI, digest
from .board_triage import TriageError


class Quarantine:
    def __init__(self, registry, graph, journal, *, call=None):
        if (not isinstance(graph, str) or not IRI.fullmatch(graph)
                or not graph.endswith('/crew/inferred')
                or not IRI.fullmatch(registry.onto)):
            raise TriageError('explicit crew/inferred graph and ontology are required; no ROOT fallback')
        if call is None:
            # Fail before a paid question when this session's writer is missing
            # or latched off by an earlier authentication refusal.
            from .quipu_auth import write_headers
            write_headers(registry.server)
        self.registry, self.graph = registry, graph
        self.call = call or self._call
        self.journal = Path(journal)
        self.journal.mkdir(parents=True, exist_ok=True, mode=0o700)
        meta = self.journal.lstat()
        if (not stat.S_ISDIR(meta.st_mode) or meta.st_uid != os.geteuid()
                or meta.st_mode & 0o077):
            raise TriageError('rank inference journal must be a private owned directory')
        data = self.call('/graphs?kind=knowledge')
        graphs = data.get('graphs')
        if (not isinstance(graphs, list) or type(data.get('count')) is not int
                or data['count'] != len(graphs)):
            raise TriageError('quarantine registry coverage UNKNOWN')
        matches = [g for g in graphs if g.get('iri') == graph]
        if len(matches) != 1:
            raise TriageError('quarantine graph absent or ambiguous; do not create or relabel it')
        selected = matches[0]
        labels = selected.get('labels') or {}
        if (not {'class','source','lifecycle','labels'} <= selected.keys()
                or selected.get('class') != 'committed' or selected.get('source') is not None
                or selected.get('lifecycle') is not None or labels.get('kind') != 'knowledge'
                or type(labels.get('trust_rank')) is not int or labels['trust_rank'] > 0
                or not isinstance(labels.get('trust_chain'), str) or not labels['trust_chain']):
            raise TriageError('quarantine trust/kind/lifecycle proof UNKNOWN')
        vocabulary = self.call('/shapes', {'action':'vocabulary'})
        classes = vocabulary.get('classes')
        if not isinstance(classes, list) or registry.onto + 'Artifact' not in classes:
            raise TriageError('answer Artifact type is not in the served vocabulary')

    def _call(self, path, body=None):
        from .quipu import request_headers
        from .quipu_auth import write_headers, refuse
        from urllib.error import HTTPError
        headers = write_headers(self.registry.server) if path == '/knot' else request_headers()
        headers = dict(headers, **{'X-Quipu-Client':'st-board-rank'})
        req = Request(self.registry.server + path,
                      data=None if body is None else json.dumps(body,sort_keys=True,separators=(',',':')).encode(), headers=headers)
        try:
            with urlopen(req, timeout=15) as response:
                raw = response.read(1024*1024+1)
        except HTTPError as error:
            if path == '/knot' and error.code == 401:
                raise refuse(self.registry.server, 'rejected (HTTP 401)') from None
            raise TriageError(f'quarantine request refused: HTTP {error.code}; no retry') from None
        if len(raw) > 1024*1024:
            raise TriageError('quarantine response capped; outcome UNKNOWN')
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get('error'):
            raise TriageError('quarantine response UNKNOWN; preserve journal, no retry')
        return value

    def _verify(self, iri, content, reference):
        onto = self.registry.onto
        query = (f'SELECT ?value ?kind ?reference WHERE {{ GRAPH <{self.graph}> {{ '
                 f'<{iri}> a <{onto}Artifact> ; <http://www.w3.org/1999/02/22-rdf-syntax-ns#value> ?value ; '
                 f'<{onto}sourceKind> ?kind ; <{onto}reference> ?reference }} }} LIMIT 2')
        data = self.call('/query', {'query':query, 'graph':self.graph})
        return (data.get('truncated') is False and type(data.get('count')) is int and data['count'] == 1
                and data.get('rows') == [dict(value=content,kind='inferred',reference=reference)])

    def __call__(self, inference):
        verdict = inference.get('verdict') or {}
        answer = verdict.get('answer') or {}
        confidence = answer.get('confidence', answer.get('noul'))
        if (inference.get('sourceKind') != 'inferred' or inference.get('plane') != 'quarantine'
                or not verdict.get('request') or not isinstance(verdict.get('model'), str) or not verdict['model']
                or type(confidence) not in (int,float) or not math.isfinite(confidence)
                or not 0 <= confidence <= 1):
            raise TriageError('rank answer lacks inferred provenance or valid confidence')
        try:
            record = dict(inference, request_digest='sha256:' + digest(verdict['request']))
            content = json.dumps(record,sort_keys=True,separators=(',',':'),ensure_ascii=False)
            identity = digest(record)
        except UnicodeEncodeError:
            # A Python surrogate is not a Unicode scalar. Refuse before the
            # durable journal or any write, rather than repairing the evidence.
            raise TriageError('rank inference contains invalid Unicode; nothing sent') from None
        iri = self.registry.onto + 'rank-verdict-' + identity
        reference = 'sha256:' + identity
        onto = self.registry.onto
        values = [('http://www.w3.org/1999/02/22-rdf-syntax-ns#type', '<'+onto+'Artifact>'),
                  ('http://www.w3.org/2000/01/rdf-schema#label', json.dumps('Jev rank proposal '+identity)),
                  (onto+'reference',json.dumps(reference)),
                  (onto+'sourceKind','"inferred"'),
                  (onto+'claim',json.dumps('Untrusted model answer; administrator acceptance required')),
                  # JSON's surrogate-pair escapes are not Turtle Unicode scalars.
                  # Keep real code points; JSON still escapes quotes/backslashes.
                  ('http://www.w3.org/1999/02/22-rdf-syntax-ns#value',json.dumps(content,ensure_ascii=False))]
        turtle = '\n'.join(f'<{iri}> <{predicate}> {value} .' for predicate,value in values)
        packet = dict(graph=self.graph,turtle=turtle,source='st-board-rank '+reference)
        raw = json.dumps(packet,sort_keys=True,separators=(',',':')).encode()
        if len(raw) > 256*1024:
            raise TriageError('rank inference request exceeded its byte budget; nothing sent')
        path = self.journal / (identity+'.json')
        try:
            fd = os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        except FileExistsError:
            raise TriageError('inference journal already exists; reconcile exact artifact, do not resend') from None
        with os.fdopen(fd,'wb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        directory = os.open(self.journal, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        # One request only. Unknown transport or readback leaves the exact body
        # in the journal; this caller never retries or switches planes.
        result = self.call('/knot',packet)
        if (result.get('conforms') is not True or type(result.get('tx_id')) is not int
                or result['tx_id'] < 0 or type(result.get('count')) is not int or result['count'] < 0):
            raise TriageError('quarantine acknowledgement rejected/UNKNOWN; preserve journal, no retry')
        if not self._verify(iri,content,reference):
            raise TriageError('quarantine artifact readback UNKNOWN; preserve journal, no retry')
        return dict(verified=True,iri=iri,graph=self.graph,tx_id=result['tx_id'],
                    journal=str(path),request_digest=record['request_digest'])
