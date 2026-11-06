"""Frozen offline store, real crew CLI: shape guard and capacity share a render."""
import json
import time
from pathlib import Path

import pytest
from rdflib import Dataset, Literal, RDF, URIRef
from shantytown import cli, seeds_plate as sp
from shantytown.sd import SdTracker, StoreProof
from shantytown.tmux import NullPanes

G = 'https://example.test/project/roster-cost'
NAMES = tuple(f'agent{i}' for i in range(14))


@pytest.fixture
def world(tmp_path, monkeypatch, capsys):
    root = tmp_path / 'world'
    (root / 'crew').mkdir(parents=True)
    for name in NAMES:
        (root / 'crew' / f'{name}.json').write_text(json.dumps({'role':'worker'}))
    data = Dataset()
    calls, constructors = [], []
    store = ['original']
    for name in NAMES:
        graph = data.graph(URIRef(G))
        subject = URIRef(sp.SEEDS + 'item/test-' + name)
        graph.add((subject, RDF.type, URIRef(sp.SCHEMA+'Action')))
        for predicate, value in [(sp.SCHEMA+'identifier','test-'+name),
                                 (sp.SCHEMA+'name','Frozen work'),
                                 (sp.SCHEMA+'agent',name),
                                 (sp.SEEDS+'ontology/status','in_progress'),
                                 (sp.SEEDS+'ontology/priority',1)]:
            graph.add((subject, URIRef(predicate), Literal(value)))
    class Response:
        status = 200
        def __init__(self,value): self.value = value
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self,size): return json.dumps(self.value).encode()[:size]
    def send(request,timeout):
        assert request.get_method() == 'POST'
        assert request.full_url == 'https://example.test/'+store[0]+'/query'
        text = json.loads(request.data)['query']
        calls.append(text)
        result = data.query(text)
        if text.startswith('ASK'):
            return Response({'result':bool(result.askAnswer)})
        rows = [{str(k): v.toPython() if isinstance(v, Literal) else str(v)
                 for k, v in row.asdict().items()} for row in result]
        return Response({'rows':rows,'count':len(rows),'truncated':False})
    original = sp._unsupported_owner_branches
    def construct(*args):
        start = time.perf_counter_ns()
        result = original(*args)
        constructors.append(time.perf_counter_ns()-start)
        return result
    def tracker(_args):
        t = SdTracker(quipu='https://example.test', prefix='test')
        t.prove_store = lambda: StoreProof(
            '--quipu',None,'https://example.test/'+store[0],'test',G)
        t._native_projection = True
        t._bd = lambda *a: pytest.fail('whole-board/SDK fallback escaped')
        return t
    monkeypatch.setattr(cli,'_tracker',tracker)
    monkeypatch.setattr(cli,'Tmux',lambda *a,**kw:NullPanes())
    monkeypatch.setattr(sp,'urlopen',send)
    monkeypatch.setattr(sp,'_unsupported_owner_branches',construct)
    def render():
        calls.clear();constructors.clear()
        # Query-only measurement uses the normal direct-read admission. No
        # cache hits or mocked projection certification can hide extra I/O.
        with sp.seeds_read_cache.direct_reads():
            assert cli.main(['--root',str(root),'--backend','seeds','crew','--local',
                             '--json','--no-priority-advice']) == cli.OK
        answer = json.loads(capsys.readouterr().out)
        with capsys.disabled():
            print(json.dumps({'requests':len(calls),'constructors':len(constructors),
                              'constructor_ns':sum(constructors),
                              'query_bytes':sum(len(q.encode()) for q in calls)}))
        return answer['agents']
    yield data, calls, constructors, store, render
    data.close()


def test_actual_roster_render_has_one_fused_guard_no_per_owner_amplification(world):
    data,calls,constructors,store,render = world
    rows = render()
    assert {r['name'] for r in rows} == set(NAMES)
    assert all(r['plate_size']==1 for r in rows)
    assert not any(q.startswith('ASK') for q in calls)
    assert sum('unsupported-owner-status' in q for q in calls)==1
    assert len(constructors)==1
    assert len(calls)==2  # one guarded candidate read, one field batch


@pytest.mark.parametrize('bad',[None,Literal('future'),URIRef('urn:status:open'),Literal('open',lang='en')])
def test_new_render_revalidates_changed_store_and_refuses_bad_status(world,bad):
    data,calls,constructors,store,render = world
    assert all(r['plate_size']==1 for r in render())
    subject = URIRef(sp.SEEDS+'item/test-agent0')
    graph = data.graph(URIRef(G))
    predicate = URIRef(sp.SEEDS+'ontology/status')
    graph.remove((subject,predicate,None))
    if bad is not None: graph.add((subject,predicate,bad))
    store[0] = 'replacement'
    assert all(r['plate_size'] is None for r in render())
    assert calls  # fresh revalidation, never stale positive admission


def test_fused_and_separate_shape_observations_render_identical_rows(world,monkeypatch):
    data,calls,constructors,store,render = world
    original = sp.RenderShapeReads.__init__
    def separate(self,**kwargs):
        original(self,inline_roster=False)
    with monkeypatch.context() as before:
        before.setattr(sp.RenderShapeReads,'__init__',separate)
        baseline = render()
        assert len(calls)==3 and sum(q.startswith('ASK') for q in calls)==1
    current = render()
    assert current == baseline
    assert len(calls)==2 and not any(q.startswith('ASK') for q in calls)
