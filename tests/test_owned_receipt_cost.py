"""Stopped-owner reconciliation over a frozen native inbox, no live store."""
import json
from types import SimpleNamespace

import pytest
from rdflib import Dataset, Literal, RDF, URIRef
from shantytown import seeds_plate as sp
from shantytown.answer import Answer
from shantytown.files import FilesRegistry
from shantytown.inbox import TrackerInbox
from shantytown.owned_work import OwnedWork
from shantytown.protocols import WorkItem
from shantytown.sd import SdTracker, StoreProof

G = 'https://example.test/project/receipt-cost'
PROOF = StoreProof('--quipu',None,'https://example.test','test',G)


@pytest.fixture
def world(tmp_path,monkeypatch):
    data, calls, creates = Dataset(), [], []
    service = OwnedWork(tmp_path)
    crew = tmp_path/'crew';crew.mkdir()
    for name, role, lead in [('worker','worker','lead'),('lead','lead','admin'),('admin','administrator',None)]:
        (crew/(name+'.json')).write_text(json.dumps({'role':role,'reports_to':lead}))
    registry = FilesRegistry(crew)
    def add(ident,body,status='closed',owner='lead'):
        graph = data.graph(URIRef(G));subject = URIRef(sp.SEEDS+'item/'+ident)
        graph.add((subject,RDF.type,URIRef(sp.SCHEMA+'Action')))
        for predicate,value in [(sp.SCHEMA+'identifier',ident),(sp.SCHEMA+'name','inbox: '+body),
                                (sp.SCHEMA+'agent',owner),(sp.SEEDS+'ontology/status',status),
                                (sp.SEEDS+'ontology/priority',2)]:
            graph.add((subject,URIRef(predicate),Literal(value)))
        return WorkItem(id=ident,title='inbox: '+body,status=status,assignee=owner,priority=2)
    for i in range(100):add('test-old-'+str(i),'retained history '+str(i))
    tracker = SdTracker(quipu=PROOF.quipu_url,prefix='test')
    monkeypatch.setattr(tracker,'prove_store',lambda:PROOF)
    monkeypatch.setattr(tracker,'_bd',lambda *a:pytest.fail('SDK/history fallback escaped'))
    def create(title,**fields):
        creates.append(title)
        return add('test-new-'+str(len(creates)),title.removeprefix('inbox: '),'open',fields['assignee'])
    monkeypatch.setattr(tracker,'create_inbox_message',create)
    class Response:
        status=200
        def __init__(self,value):self.value=value
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,size):return json.dumps(self.value).encode()[:size]
    def send(request,timeout):
        assert request.get_method()=='POST'
        assert request.full_url==PROOF.quipu_url+'/query'
        text=json.loads(request.data)['query']
        result=data.query(text)
        rows=[{str(k):v.toPython() if isinstance(v,Literal) else str(v)
               for k,v in row.asdict().items()} for row in result]
        calls.append({'query':text,'subjects':{r['subject'] for r in rows if r.get('subject')}})
        return Response({'rows':rows,'count':len(rows),'truncated':False})
    monkeypatch.setattr(sp,'urlopen',send)
    box = TrackerInbox(tracker,lambda:pytest.fail('board hydration escaped'),items_for=tracker.inbox_items)
    rows = [dict(id='test-work',title='urgent',assignee='worker',priority=0,status='open')]
    state = SimpleNamespace(data=data,calls=calls,creates=creates,service=service,box=box,
                            tracker=tracker,add=add,root=tmp_path)
    def tick():
        with sp.seeds_read_cache.direct_reads():
            return state.service.tick(registry,lambda _:Answer.complete_read(rows,how='frozen owner'),box,now=100)
    state.tick = tick
    service.stop('worker',at=100)
    yield state
    data.close()


def test_known_delivery_does_not_select_retained_history(world):
    assert world.tick()==[('worker','delivered')]
    assert len(world.creates)==1
    assert len(world.calls)==2  # worker unread observation plus one exact receipt
    assert max(len(c['subjects']) for c in world.calls)==1
    state = world.service.snapshot()['worker']
    assert state['receipt']=='test-new-1'


def test_known_id_is_saved_before_metadata_io_and_recovers_after_crash(world,monkeypatch):
    def crash(*args,**kwargs):
        assert world.service.snapshot()['worker']['receipt']=='test-new-1'
        raise SystemExit('crash after durable id, before metadata')
    with monkeypatch.context() as m:
        m.setattr(world.box,'find_delivery_receipt',crash)
        with pytest.raises(SystemExit):world.tick()
    assert world.service.snapshot()['worker']['notice']=='attempting'
    world.service = OwnedWork(world.root)
    # The same local state must recover, without a second durable create.
    assert world.tick()==[('worker','reconciled')]
    assert len(world.creates)==1
    assert world.service.snapshot()['worker']['notice']=='delivered'


def lose_receipt(world):
    with world.service.locked() as states:
        states['worker']['notice'] = 'unknown'
        states['worker'].pop('receipt', None)
    world.calls.clear()
    return world.service.snapshot()['worker']['body']


def test_unknown_id_recovers_closed_receipt_without_history_hydration(world):
    assert world.tick()==[('worker','delivered')]
    body = lose_receipt(world)
    subject = URIRef(sp.SEEDS+'item/test-new-1')
    world.data.graph(URIRef(G)).set((subject,URIRef(sp.SEEDS+'ontology/status'),Literal('closed')))
    world.service = OwnedWork(world.root)
    assert world.tick()==[('worker','reconciled')]
    assert len(world.creates)==1
    assert len(world.calls)==2
    assert max(len(c['subjects']) for c in world.calls)==1
    assert 'LIMIT 3' in world.calls[0]['query']
    assert world.service.snapshot()['worker']['body']==body


def test_unknown_id_ambiguous_marker_stays_unknown_and_never_resends(world):
    from shantytown.answer import PartialAnswer
    assert world.tick()==[('worker','delivered')]
    body = lose_receipt(world)
    world.add('test-duplicate',body)
    with pytest.raises(PartialAnswer,match='ambiguous'):
        world.tick()
    assert len(world.creates)==1
    assert world.service.snapshot()['worker']['notice']=='unknown'
    assert len(world.calls)==1  # identity ambiguity refuses before hydration


def test_unknown_id_missing_receipt_is_not_resend_permission(world):
    assert world.tick()==[('worker','delivered')]
    lose_receipt(world)
    world.data.graph(URIRef(G)).remove((URIRef(sp.SEEDS+'item/test-new-1'),None,None))
    assert world.tick()==[('worker','delivery UNKNOWN; no resend')]
    assert len(world.creates)==1
    assert len(world.calls)==1


def test_failed_known_id_never_falls_back_to_marker_or_history(world,monkeypatch):
    from shantytown.answer import PartialAnswer
    assert world.tick()==[('worker','delivered')]
    with world.service.locked() as states:states['worker']['notice']='unknown'
    world.data.graph(URIRef(G)).remove((URIRef(sp.SEEDS+'item/test-new-1'),None,None))
    monkeypatch.setattr(world.tracker,'inbox_delivery',lambda *a:pytest.fail('marker fallback escaped'))
    with pytest.raises(PartialAnswer,match='missing'):
        world.tick()
    assert len(world.creates)==1
    assert world.service.snapshot()['worker']['receipt']=='test-new-1'


def test_unavailable_legacy_marker_reader_stays_unknown_after_bounded_refusal(world,monkeypatch):
    import subprocess
    from shantytown.answer import PartialAnswer
    assert world.tick()==[('worker','delivered')]
    lose_receipt(world)
    world.tracker._native_projection=False
    def unavailable(*args):
        assert args[args.index('--limit')+1]=='3' and '--all' in args
        return subprocess.CompletedProcess(args,2,'','legacy unavailable')
    monkeypatch.setattr(world.tracker,'_bd',unavailable)
    with pytest.raises(PartialAnswer,match='unavailable'):
        world.tick()
    assert not world.calls
    assert len(world.creates)==1


def test_truncated_marker_observation_cannot_become_absence(world,monkeypatch):
    from shantytown.answer import PartialAnswer
    from shantytown import seeds_inbox
    assert world.tick()==[('worker','delivered')]
    lose_receipt(world)
    monkeypatch.setattr(seeds_inbox,'marker_ids',lambda *a,**kw:Answer.capped(
        [],how='incomplete transport fixture',caveat='truncated response'))
    with pytest.raises(PartialAnswer,match='truncated'):
        world.tick()
    assert len(world.creates)==1


@pytest.mark.parametrize('fault',['none','incomplete','cap','ambiguous','foreign','status','missing'])
def test_legacy_marker_lookup_is_bounded_and_preserves_uncertainty(world,monkeypatch,fault):
    import subprocess
    from shantytown.answer import PartialAnswer
    assert world.tick()==[('worker','delivered')]
    body=lose_receipt(world)
    world.tracker._native_projection=False
    row=dict(id='test-new-1',title='inbox: '+body,status='closed',assignee='lead',priority=2)
    rows=[row]
    if fault=='foreign':row['assignee']='other'
    if fault=='status':row['status']='future'
    if fault=='missing':row.pop('priority')
    if fault in ('cap','ambiguous'):
        rows += [{**row,'id':'test-extra-'+str(i)} for i in range(2 if fault=='cap' else 1)]
    def legacy(*args):
        assert args[args.index('--assignee')+1]=='lead'
        assert args[args.index('--limit')+1]=='3' and '--all' in args
        assert args[args.index('--title-contains')+1]==body.split(' ',1)[0]
        return subprocess.CompletedProcess(args,0,json.dumps(dict(
            issues=rows,total=len(rows),has_more=fault=='incomplete')),'')
    monkeypatch.setattr(world.tracker,'_bd',legacy)
    if fault=='none':assert world.tick()==[('worker','reconciled')]
    else:
        with pytest.raises(PartialAnswer):world.tick()
        assert world.service.snapshot()['worker']['notice']=='unknown'
    assert len(world.creates)==1


def test_marker_lookup_accepts_the_selected_short_recipient_alias(world):
    world.add('test-alias','marker payload',owner='lead')
    with sp.seeds_read_cache.direct_reads():
        found=world.box.find_delivery('crew/lead','marker')
    assert found.id=='test-alias' and found.read
