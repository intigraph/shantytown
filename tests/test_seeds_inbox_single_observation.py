"""One fresh read retains format, owner, message and exact receipt guards."""
import pytest
from rdflib import Dataset, Literal, RDF, URIRef
from shantytown import seeds_inbox as si, seeds_plate as sp
from shantytown.sd import SdTracker, StoreProof
from shantytown.inbox import TrackerInbox
from shantytown.answer import PartialAnswer

G = 'https://example.test/project/inbox'
PROOF = StoreProof('--quipu', None, 'https://example.test', 'demo', G)


def add(data, ident='demo-message', *, graph=G, owner='worker', status='open',
        title='inbox: marker body'):
    g = data.graph(URIRef(graph))
    s = URIRef(sp.SEEDS+'item/'+ident)
    g.add((s, RDF.type, URIRef(sp.SCHEMA+'Action')))
    for p, v in [(sp.SCHEMA+'identifier', ident), (sp.SCHEMA+'name', title),
                 (sp.SCHEMA+'agent', owner), (sp.SEEDS+'ontology/status', status),
                 (sp.SEEDS+'ontology/priority', 1)]:
        if v is not None:
            g.add((s, URIRef(p), Literal(v)))
    return g, s


@pytest.fixture
def wire(monkeypatch):
    data, calls = Dataset(), []
    def query(proof, text, timeout):
        calls.append(text)
        result = data.query(text)
        rows = [{str(k): v.toPython() if isinstance(v, Literal) else str(v)
                 for k, v in row.asdict().items()} for row in result]
        return {'rows': rows, 'count': len(rows), 'truncated': False}
    monkeypatch.setattr(sp, '_query', query)
    yield data, calls
    data.close()


def test_one_read_combines_prefixes_graphs_owners_and_format(wire):
    data, calls = wire
    add(data)
    add(data, 'demo-legacy', graph=G+'#seeds-ephemeral', owner='crew/worker',
        title='mail: legacy', status='deferred')
    add(data, 'demo-closed', status='closed')
    add(data, 'demo-work', title='ordinary work')
    add(data, 'demo-foreign', owner='other')
    rows = si.read(PROOF, 'crew/worker').exact()
    assert {r['id'] for r in rows} == {'demo-message', 'demo-legacy'}
    assert len(calls) == 1 and calls[0].startswith('SELECT')
    assert 'revision' in calls[0] and 'unsupported-owner-status' in calls[0]
    assert not any(p in calls[0] for p in ('description', 'notes', 'retained'))


def test_empty_does_not_cache_an_absence(wire):
    data, calls = wire
    assert si.read(PROOF, 'worker').exact() == []
    add(data)
    assert len(si.read(PROOF, 'worker').exact()) == 1
    assert len(calls) == 2


@pytest.mark.parametrize('bad', ['alien', None])
def test_bad_owned_nonmessage_status_still_refuses(wire, bad):
    data, calls = wire
    add(data)
    add(data, 'demo-bad', title='ordinary work', status=bad)
    result = si.read(PROOF, 'worker')
    assert not result.complete and len(calls) == 1


def test_closed_receipt_and_exact_identity(wire):
    data, calls = wire
    add(data, status='closed')
    rows = si.read(PROOF, 'worker', identifiers=['demo-message']).exact()
    assert len(rows) == 1 and rows[0]['status'] == 'closed' and len(calls) == 1
    assert not si.read(PROOF, 'other', identifiers=['demo-message']).complete
    assert not si.read(PROOF, 'worker', identifiers=['demo-missing']).complete


def test_shadow_and_ambiguous_value_refuse(wire):
    data, calls = wire
    g, s = add(data)
    g.add((s, URIRef(sp.SEEDS+'ontology/priority'), Literal(2)))
    assert not si.read(PROOF, 'worker').complete
    g.remove((s, URIRef(sp.SEEDS+'ontology/priority'), Literal(2)))
    add(data, graph=G+'#seeds-ephemeral')
    assert not si.read(PROOF, 'worker').complete


def test_exact_ack_validates_whole_selection_before_any_close(wire, monkeypatch):
    data, calls = wire
    add(data)
    add(data, 'demo-foreign', owner='other')
    t = SdTracker(quipu=PROOF.quipu_url, prefix='demo')
    monkeypatch.setattr(t, 'prove_store', lambda: PROOF)
    writes = []
    monkeypatch.setattr(t, 'update', lambda *a, **kw: writes.append((a, kw)))
    monkeypatch.setattr(t, 'get', lambda *a: pytest.fail('SDK hydration'))
    box = TrackerInbox(t, lambda: [], items_for=t.inbox_items)
    with pytest.raises(PartialAnswer):
        box.mark_read('worker', ['demo-message', 'demo-foreign'])
    assert not writes
    assert [m.id for m in box.mark_read('worker', ['demo-message'])] == ['demo-message']
    assert len(writes) == 1 and writes[0][1] == {'status':'closed'}


def test_unknown_format_read_never_permits_fallback(wire, monkeypatch):
    data, calls = wire
    t = SdTracker(quipu=PROOF.quipu_url, prefix='demo')
    monkeypatch.setattr(t, 'prove_store', lambda: PROOF)
    monkeypatch.setattr(t, '_owner_rows', lambda *a, **kw: pytest.fail('unproven fallback'))
    monkeypatch.setattr(sp, '_query', lambda *a, **kw: (_ for _ in ()).throw(OSError('unreadable')))
    assert not t.inbox_items('worker').complete


def test_positive_legacy_marker_permits_only_sdk_compatibility(wire, monkeypatch):
    data, calls = wire
    data.graph(URIRef(G)).add((URIRef(G+'/legacy'), URIRef(sp.SEEDS+'ontology/revision'), Literal(1)))
    t = SdTracker(quipu=PROOF.quipu_url, prefix='demo')
    monkeypatch.setattr(t, 'prove_store', lambda: PROOF)
    fallback = []
    from shantytown.answer import Answer
    def legacy(*args, **kwargs):
        fallback.append((args, kwargs))
        return Answer.complete_read([], how='positive legacy fixture')
    monkeypatch.setattr(t, '_owner_rows', legacy)
    assert t.inbox_items('worker').exact() == []
    assert len(calls) == 1 and len(fallback) == 1
    assert t._native_projection is False


def test_ack_empty_is_noop_and_large_selection_is_bounded(wire, monkeypatch):
    data, calls = wire
    ids = ['demo-message-'+str(i) for i in range(26)]
    for i in ids:
        add(data, i)
    t = SdTracker(quipu=PROOF.quipu_url, prefix='demo')
    monkeypatch.setattr(t, 'prove_store', lambda: PROOF)
    writes = []
    monkeypatch.setattr(t, 'update', lambda i, **kw: writes.append(i))
    box = TrackerInbox(t, lambda: [], items_for=t.inbox_items)
    assert box.mark_read('worker', []) == [] and not calls and not writes
    assert [m.id for m in box.mark_read('worker', ids)] == ids
    assert len(calls) == 2 and writes == ids
