import json
from types import SimpleNamespace as NS

import pytest
from shantytown.rank_quarantine import Quarantine
from shantytown.board_triage import TriageError

ONTO='https://example.org/ontology/'
GRAPH='https://example.org/plane/crew/inferred'


class Server:
    def __init__(self):
        self.calls=[];self.packet=None;self.accept=True;self.present=True;self.rank=0;self.kind='knowledge'
        self.reference=None;self.content=None
    def __call__(self,path,body=None):
        self.calls.append((path,body))
        if path.startswith('/graphs'):
            return dict(count=1,graphs=[dict(iri=GRAPH,source=None,lifecycle=None,
                **{'class':'committed'},labels=dict(trust_rank=self.rank,trust_chain='urn:chain',kind=self.kind))])
        if path=='/shapes':return dict(classes=[ONTO+'Artifact'])
        if path=='/knot':
            self.packet=body
            triples=body['turtle'].splitlines()
            for line in triples:
                if '1999/02/22-rdf-syntax-ns#value>' in line:
                    self.content=json.loads(line.split('> ',2)[2][:-2])
                if ONTO+'reference>' in line:
                    self.reference=json.loads(line.split('> ',2)[2][:-2])
            return dict(conforms=self.accept,tx_id=2,count=6)
        if path=='/query':
            assert body['graph']==GRAPH and 'GRAPH <'+GRAPH+'>' in body['query']
            rows=[dict(value=self.content,kind='inferred',reference=self.reference)] if self.present else []
            return dict(truncated=False,count=len(rows),rows=rows)
        raise AssertionError(path)


def inference():
    return dict(item='task-1',sourceKind='inferred',plane='quarantine',rules_digest='r',
                verdict=dict(request={'state':'fixture'},model='test-model',usage={},
                             answer=dict(choice='none-of-these',confidence=.8)))


def writer(tmp_path,server):
    return Quarantine(NS(onto=ONTO,server='http://example.invalid'),GRAPH,tmp_path/'journal',call=server)


def test_writes_one_inferred_artifact_and_verifies_reader_route(tmp_path):
    server=Server();sink=writer(tmp_path,server);receipt=sink(inference())
    assert receipt['verified'] is True and receipt['graph']==GRAPH
    assert server.packet['graph']==GRAPH
    assert '"inferred"' in server.packet['turtle']
    assert ONTO+'Artifact>' in server.packet['turtle']
    assert server.content is not None and json.loads(server.content)['verdict']['model']=='test-model'
    journal=list((tmp_path/'journal').glob('*.json'));assert len(journal)==1
    assert json.loads(journal[0].read_text())==server.packet
    assert journal[0].stat().st_mode & 0o777==0o600
    with pytest.raises(TriageError,match='already exists'):
        sink(inference())
    assert [path for path,_ in server.calls].count('/knot')==1


def test_root_and_trusted_graphs_refuse_before_model_or_write(tmp_path):
    server=Server()
    with pytest.raises(TriageError,match='no ROOT fallback'):
        Quarantine(NS(onto=ONTO), 'urn:quipu:graph:root',tmp_path/'journal',call=server)
    assert server.calls==[]
    server.rank=30
    with pytest.raises(TriageError,match='trust/kind'):
        writer(tmp_path,server)
    assert not any(path=='/knot' for path,_ in server.calls)


@pytest.mark.parametrize('accepted,present',[(False,True),(True,False)])
def test_shacl_refusal_or_unknown_readback_never_retries(tmp_path,accepted,present):
    server=Server();server.accept=accepted;server.present=present;sink=writer(tmp_path,server)
    with pytest.raises(TriageError,match='UNKNOWN'):
        sink(inference())
    assert len(list((tmp_path/'journal').glob('*.json')))==1
    assert [path for path,_ in server.calls].count('/knot')==1


def test_missing_credential_or_transport_failure_preserves_exact_request(tmp_path):
    server=Server();sink=writer(tmp_path,server);original=sink.call
    def fail(path,body=None):
        if path=='/knot':raise TimeoutError('synthetic transport timeout')
        return original(path,body)
    sink.call=fail
    with pytest.raises(TimeoutError):sink(inference())
    assert len(list((tmp_path/'journal').glob('*.json')))==1
    # A later attempt cannot consume a fresh transport budget for this artifact.
    with pytest.raises(TriageError,match='already exists'):sink(inference())


def test_wire_bytes_equal_journal_and_headers_are_not_recorded(tmp_path,monkeypatch):
    from shantytown import quipu,quipu_auth
    server=Server();sink=writer(tmp_path,server);captured=[]
    monkeypatch.setattr(quipu_auth,'write_headers',lambda _:dict(Authorization='Bearer SYNTHETIC'))
    class Response:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def read(self,n):return b'{"conforms":true,"tx_id":3,"count":6}'
    def open_request(request,**kw):captured.append(request);return Response()
    monkeypatch.setattr('shantytown.rank_quarantine.urlopen',open_request)
    original=sink.call
    sink.call=lambda path,body=None:sink._call(path,body) if path=='/knot' else original(path,body)
    sink._verify=lambda *a:True
    sink(inference())
    journal=next((tmp_path/'journal').glob('*.json'))
    assert journal.read_bytes()==captured[0].data
    assert b'SYNTHETIC' not in journal.read_bytes()


def test_missing_or_latched_writer_refuses_before_graph_probe_or_model(tmp_path,monkeypatch):
    from shantytown import quipu_auth
    def missing(_):raise quipu_auth.CredentialRefused('fixture writer disabled')
    monkeypatch.setattr(quipu_auth,'write_headers',missing)
    with pytest.raises(quipu_auth.CredentialRefused):
        Quarantine(NS(onto=ONTO,server='http://example.invalid'),GRAPH,tmp_path/'journal')
    assert not (tmp_path/'journal').exists()


class RDFServer(Server):
    """Read the sent Turtle through an RDF parser, rather than JSON decoding it."""
    def __call__(self, path, body=None):
        if path != '/knot':
            return super().__call__(path, body)
        from rdflib import Graph, URIRef
        from rdflib.namespace import RDF
        self.calls.append((path, body))
        self.packet = body
        graph = Graph().parse(data=body['turtle'], format='turtle')
        subject = next(graph.subjects(RDF.type, URIRef(ONTO + 'Artifact')))
        self.content = str(graph.value(subject, RDF.value))
        self.reference = str(graph.value(subject, URIRef(ONTO + 'reference')))
        assert len(graph) == 6
        return dict(conforms=self.accept, tx_id=2, count=6)


@pytest.mark.parametrize('text', [
    'astral \U0001f680 and \U0001d11e',
    'quotes " slash \\ tabs\t newline\n return\r backspace\b formfeed\f',
    'controls ' + ''.join(chr(n) for n in range(32)) + '\x7f',
    'BMP café 中文 and line separators \u2028\u2029',
    '" . <urn:injected> <urn:predicate> "payload',
])
def test_rdf_literal_round_trip_preserves_exact_record(tmp_path, text):
    server = RDFServer()
    payload = inference()
    payload['verdict']['answer']['explanation'] = text
    receipt = writer(tmp_path, server)(payload)
    assert receipt['verified'] is True
    assert json.loads(server.content)['verdict']['answer']['explanation'] == text
    assert server.packet['graph'] == GRAPH
    assert [path for path, _ in server.calls].count('/knot') == 1
    journal = next((tmp_path / 'journal').glob('*.json'))
    assert json.loads(journal.read_bytes()) == server.packet


@pytest.mark.parametrize('text', ['\ud800', '\udfff', '\ud83d\ude80'])
@pytest.mark.parametrize('location', ['answer', 'request'])
def test_surrogates_refused_before_journal_or_write(tmp_path, text, location):
    server = RDFServer()
    payload = inference()
    payload['verdict'][location]['explanation'] = text
    with pytest.raises(TriageError, match='Unicode'):
        writer(tmp_path, server)(payload)
    assert not any(path == '/knot' for path, _ in server.calls)
    assert list((tmp_path / 'journal').glob('*.json')) == []
