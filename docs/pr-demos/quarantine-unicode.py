"""Offline demonstration; use --source to select the source checkout."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

parser = argparse.ArgumentParser()
parser.add_argument('--source', required=True)
args = parser.parse_args()
sys.path.insert(0, str(Path(args.source).resolve()))
from rdflib import Graph, URIRef
from rdflib.namespace import RDF
from shantytown.rank_quarantine import Quarantine

ONTO = 'https://example.org/ontology/'
GRAPH = 'https://example.org/plane/crew/inferred'


class Server:
    def __init__(self):
        self.writes = 0
        self.content = self.reference = None

    def __call__(self, path, body=None):
        if path.startswith('/graphs'):
            return dict(count=1, graphs=[dict(iri=GRAPH, source=None, lifecycle=None,
                **{'class': 'committed'}, labels=dict(trust_rank=0, trust_chain='urn:fixture', kind='knowledge'))])
        if path == '/shapes':
            return dict(classes=[ONTO + 'Artifact'])
        if path == '/knot':
            assert body['graph'] == GRAPH
            self.writes += 1
            graph = Graph().parse(data=body['turtle'], format='turtle')
            subject = next(graph.subjects(RDF.type, URIRef(ONTO + 'Artifact')))
            assert len(graph) == 6
            self.content = str(graph.value(subject, RDF.value))
            self.reference = str(graph.value(subject, URIRef(ONTO + 'reference')))
            return dict(conforms=True, tx_id=1, count=6)
        if path == '/query':
            assert body['graph'] == GRAPH
            return dict(truncated=False, count=1, rows=[dict(value=self.content, kind='inferred', reference=self.reference)])
        raise AssertionError(path)


for label, text in [('astral', '\U0001f680 and \U0001d11e'),
                    ('escaping', 'quote " backslash \\ newline\n control\x00'),
                    ('lone-surrogate', '\ud800')]:
    payload = dict(item='fixture', sourceKind='inferred', plane='quarantine',
                   verdict=dict(request={'fixture': True}, model='fixture',
                                answer=dict(confidence=.8, explanation=text)))
    server = Server()
    with tempfile.TemporaryDirectory() as temporary:
        sink = Quarantine(SimpleNamespace(onto=ONTO, server='http://example.invalid'),
                          GRAPH, Path(temporary) / 'journal', call=server)
        try:
            receipt = sink(payload)
            outcome = 'verified' if receipt['verified'] else 'unknown'
        except Exception as error:
            outcome = type(error).__name__
        exact = False
        if server.content is not None:
            try:
                exact = json.loads(server.content)['verdict']['answer']['explanation'] == text
            except (ValueError, KeyError):
                pass
        print(json.dumps(dict(case=label, outcome=outcome, exact_codepoints=exact,
                              fixture_writes=server.writes,
                              journal_count=len(list((Path(temporary) / 'journal').glob('*.json'))),
                              live_writes=0), sort_keys=True))
