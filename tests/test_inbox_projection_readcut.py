"""The inbox guard shares its candidate snapshot; field validation stays strict."""
import pytest
from rdflib import Dataset, Literal, RDF, URIRef
from shantytown import seeds_plate as sp
from shantytown.sd import StoreProof

G = 'https://example.test/project/inbox'
PROOF = StoreProof('--quipu', None, 'https://example.test', 'demo', G)


def add(data, ident='demo-message', *, status='open', owner='worker', graph=G,
        title='inbox: positive receipt'):
    target = data.graph(URIRef(graph))
    subject = URIRef(sp.SEEDS + 'item/' + ident)
    target.add((subject, RDF.type, URIRef(sp.SCHEMA + 'Action')))
    for predicate, value in [(sp.SCHEMA+'identifier', ident), (sp.SCHEMA+'name', title),
                             (sp.SCHEMA+'agent', owner),
                             (sp.SEEDS+'ontology/status', status),
                             (sp.SEEDS+'ontology/priority', 1)]:
        target.add((subject, URIRef(predicate), Literal(value)))
    return target, subject


@pytest.fixture
def wire(monkeypatch):
    data, calls = Dataset(), []
    def query(proof, text, timeout):
        calls.append(text)
        result = data.query(text)
        if result.type == 'ASK':
            return {'result': bool(result.askAnswer)}
        rows = [{str(k): v.toPython() if isinstance(v, Literal) else str(v)
                 for k, v in row.asdict().items()} for row in result]
        return {'rows': rows, 'count': len(rows), 'truncated': False}
    monkeypatch.setattr(sp, '_query', query)
    yield data, calls
    data.close()


def test_populated_inbox_keeps_rows_with_two_requests(wire):
    data, calls = wire
    add(data)
    add(data, 'demo-legacy', owner='crew/worker', graph=G+'#seeds-ephemeral',
        status='deferred', title='mail: legacy')
    rows = sp.owner_rows(PROOF, 'crew/worker', messages_only=True).exact()
    assert {r['id'] for r in rows} == {'demo-message', 'demo-legacy'}
    assert len(calls) == 2
    assert not any(q.startswith('ASK') for q in calls)


def test_empty_inbox_has_one_request_and_no_cross_read_cache(wire):
    data, calls = wire
    assert sp.owner_rows(PROOF, 'worker', messages_only=True).exact() == []
    assert len(calls) == 1
    add(data)
    assert len(sp.owner_rows(PROOF, 'worker', messages_only=True).exact()) == 1
    assert len(calls) == 3


@pytest.mark.parametrize('status', ['alien', None])
def test_bad_nonmessage_owned_status_still_refuses(wire, status):
    data, calls = wire
    add(data)
    target, subject = add(data, 'demo-work', title='ordinary work', status=status or 'open')
    if status is None:
        target.remove((subject, URIRef(sp.SEEDS+'ontology/status'), None))
    result = sp.owner_rows(PROOF, 'worker', messages_only=True)
    assert not result.complete
    assert 'unsupported or absent status' in result.caveat
    assert len(calls) == 1, 'do not hydrate after a guard counterexample'


def test_foreign_bad_status_does_not_poison_owner_and_closed_receipts_preserved(wire):
    data, calls = wire
    add(data, status='closed')
    add(data, 'demo-foreign', owner='other', status='alien')
    assert sp.owner_rows(PROOF, 'worker', messages_only=True).exact() == []
    rows = sp.owner_rows(PROOF, 'worker', messages_only=True, include_closed=True).exact()
    assert [r['id'] for r in rows] == ['demo-message']


def test_ephemeral_shadow_remains_unknown(wire):
    data, calls = wire
    add(data)
    add(data, graph=G+'#seeds-ephemeral')
    assert not sp.owner_rows(PROOF, 'worker', messages_only=True).complete


def test_non_inbox_projection_shares_fresh_guard_with_candidates(wire):
    data, calls = wire
    add(data, title='ordinary work')
    assert len(sp.owner_rows(PROOF, 'worker').exact()) == 1
    assert len(calls) == 2 and not any(q.startswith('ASK') for q in calls)


@pytest.mark.parametrize('options', [{}, {'capacity': True}, {'decision': True},
                                    {'include_deferred': True}])
def test_owner_projection_fresh_guard_retains_positive_and_refuses_bad_work(wire, options):
    data, calls = wire
    add(data, title='ordinary work')
    assert [r['id'] for r in sp.owner_rows(PROOF, 'worker', **options).exact()] == ['demo-message']
    assert len(calls) == 2
    add(data, 'demo-bad', title='different ordinary work', status='alien')
    result = sp.owner_rows(PROOF, 'worker', **options)
    assert not result.complete and 'unsupported or absent status' in result.caveat
    assert len(calls) == 3, 'a fresh guard must refuse before field hydration'


def test_empty_owner_guard_and_foreign_bad_status(wire):
    data, calls = wire
    add(data, 'demo-foreign', owner='other', title='foreign work', status='alien')
    assert sp.owner_rows(PROOF, 'worker').exact() == []
    assert len(calls) == 1
    target, subject = add(data, title='owned work')
    target.remove((subject, URIRef(sp.SEEDS+'ontology/status'), None))
    result = sp.owner_rows(PROOF, 'worker')
    assert not result.complete and 'unsupported or absent status' in result.caveat
    assert len(calls) == 2


def test_native_inbox_guard_and_fields_use_two_requests(monkeypatch, tmp_path):
    """Exercise the composed relation on the real server, never production."""
    import os
    import socket
    import subprocess
    import time
    import urllib.parse
    import urllib.request
    binary = os.environ.get('SHANTYTOWN_TEST_QUIPU_SERVER')
    if not binary:
        pytest.skip('set SHANTYTOWN_TEST_QUIPU_SERVER for private native control')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    child = subprocess.Popen([binary, '--db', str(tmp_path/'q.db'),
                              '--bind', f'127.0.0.1:{port}'], cwd=tmp_path,
                             env=dict(os.environ, HOME=str(tmp_path)),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(url+'/health', timeout=1).close()
                break
            except OSError:
                if child.poll() is not None:
                    pytest.fail('private native fixture exited during startup')
                time.sleep(.1)
        def update(text):
            request = urllib.request.Request(url+'/update',
                data=urllib.parse.urlencode({'update':text}).encode(),
                headers={'Content-Type':'application/x-www-form-urlencoded',
                         'X-Quipu-Client':'seeds'})
            with urllib.request.urlopen(request, timeout=5) as response:
                assert response.status == 200
        data = Dataset()
        add(data)
        add(data, 'demo-legacy', owner='crew/worker', title='mail: legacy',
            graph=G+'#seeds-ephemeral', status='deferred')
        add(data, 'demo-receipt', status='closed')
        add(data, 'demo-foreign', owner='other', status='alien')
        for graph in data.graphs():
            facts = ' '.join(f'{s.n3()} {p.n3()} {o.n3()} .' for s,p,o in graph)
            if facts:
                update(f'INSERT DATA {{ GRAPH <{graph.identifier}> {{ {facts} }} }}')
        data.close()
        calls = []
        original = sp._query
        def counted(*args, **kw):
            calls.append(args[1])
            return original(*args, **kw)
        monkeypatch.setattr(sp, '_query', counted)
        proof = StoreProof('--quipu', None, url, 'demo', G)
        assert {r['id'] for r in sp.owner_rows(proof, 'crew/worker', messages_only=True).exact()} == {
            'demo-message', 'demo-legacy'}
        assert len(calls) == 2
        assert {r['id'] for r in sp.owner_rows(proof, 'crew/worker', messages_only=True,
                                              include_closed=True).exact()} == {
            'demo-message', 'demo-legacy', 'demo-receipt'}
        assert len(calls) == 4
        update(f'INSERT DATA {{ GRAPH <{G}> {{ <{sp.SEEDS}item/demo-work> a <{sp.SCHEMA}Action> ; '
               f'<{sp.SCHEMA}identifier> "demo-work" ; <{sp.SCHEMA}name> "ordinary work" ; '
               f'<{sp.SCHEMA}agent> "worker" ; <{sp.SEEDS}ontology/status> "open" ; '
               f'<{sp.SEEDS}ontology/priority> 1 . }} }}')
        assert [r['id'] for r in sp.owner_rows(proof, 'worker').exact()] == ['demo-work']
        assert len(calls) == 6
        # A bad ordinary task (not a message) must still invalidate the read.
        update(f'INSERT DATA {{ GRAPH <{G}> {{ <{sp.SEEDS}item/demo-bad> a <{sp.SCHEMA}Action> ; '
               f'<{sp.SCHEMA}agent> "worker" ; <{sp.SEEDS}ontology/status> "alien" . }} }}')
        result = sp.owner_rows(proof, 'worker', messages_only=True)
        assert not result.complete and 'unsupported or absent status' in result.caveat
        assert len(calls) == 7
        result = sp.owner_rows(proof, 'worker')
        assert not result.complete and 'unsupported or absent status' in result.caveat
        assert len(calls) == 8
        print('native inbox/owner PASS: populated reads 2 requests each; fresh bad-owner guard 1/refused')
    finally:
        child.terminate()
        child.wait(timeout=10)
