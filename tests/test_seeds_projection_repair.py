"""A changed payload repairs its fields; membership/store changes restart."""
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
import pytest
from shantytown import seeds_plate as plate, seeds_read_cache as cache

G = 'https://example.test/repair'
A, B = [plate.SEEDS + 'item/' + key for key in ('test-a', 'test-b')]

@pytest.fixture
def changing(monkeypatch, tmp_path):
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path / 'cache'))
    monkeypatch.setenv('ST_SEEDS_READ_CACHE', '0')
    monkeypatch.setattr(plate, 'owner_shape_supported', lambda *a, **kw: True)
    state = dict(tx=10, store='original', candidates=0, fields=[], records=[], mode='entity', labels={A:'old-a', B:'old-b'})
    monkeypatch.setattr(cache, '_watermark', lambda *args: (state['store'], state['tx']))
    class Response:
        status=200
        def __init__(self, body): self.body=body
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self,size): return json.dumps(self.body).encode()
    def send(request, timeout):
        if request.get_method()=='POST':
            query=json.loads(request.data)['query']
            if '?predicate ?value' not in query:
                state['candidates']+=1
                state.setdefault('candidate_queries',[]).append(query)
                subjects=[B] if state.get('moved') else [A,B]
                rows=[dict(subject=s, graph=G) for s in subjects]
            else:
                subjects=[s for s in (A,B) if '<'+s+'>' in query]
                state['fields'].append(subjects)
                inverse={v:k for k,v in plate.FIELDS.items()}
                rows=[]
                for subject in subjects:
                    values=dict(id=subject.rsplit('/',1)[1],title='work',status='open',assignee='worker',priority=1,issue_type='task',labels=state['labels'][subject])
                    if state['mode']=='bad-fields' and len(state['fields'])==2: values['priority']={'unsupported':'bad'}
                    rows.extend(dict(subject=subject,graph=G,predicate=inverse[k],value=v) for k,v in values.items())
                n=len(state['fields']);mode=state['mode']
                if n==1 or mode=='always' or (mode in ('second','late-membership','late-store','epoch') and n==2):
                    subject=B if n==2 and mode in ('second','late-membership','late-store','epoch') else A
                    state['tx']+=1;state['labels'][subject]='new-'+subject[-1]
                    attribute=plate.SCHEMA+'keywords'
                    if mode=='membership' or (mode=='late-membership' and n==2): attribute=plate.SCHEMA+'agent';state['moved']=True
                    if mode=='store' or (mode=='late-store' and n==2): state['store']='replacement';state['records']=[]
                    else: state['records'].append(dict(tx=state['tx'],graph=G,entity=subject,attribute=attribute,op='assert'))
            return Response(dict(rows=rows,count=len(rows),truncated=False))
        q=parse_qs(urlsplit(request.full_url).query);since=int(q['since'][0]);graph=q['graph'][0]
        records=[r.copy() for r in state['records'] if r['graph']==graph and r['tx']>since]
        if state['mode']=='malformed' and records:records[-1].pop('attribute')
        return Response(dict(since=since,records=records,next_tx=max((r['tx'] for r in records),default=since),watermark_tx=state['tx'],capture='new_values',source=dict(store_id=state['store'],log_epoch=('replacement' if state['mode']=='epoch' and len(state['fields'])>1 else 'epoch'))))
    monkeypatch.setattr(plate,'urlopen',send)
    return SimpleNamespace(quipu_url='https://example.test',graph=G),state

def test_returned_payload_reloads_only_changed_subject(changing):
    proof,state=changing
    rows=plate.owner_rows(proof,'worker').exact()
    assert state['candidates']==1
    assert state['fields']==[[A,B],[A]]
    assert {r['id']:r['labels'] for r in rows}=={'test-a':['new-a'],'test-b':['old-b']}

def test_change_during_repair_is_fenced_and_repaired_too(changing):
    proof,state=changing;state['mode']='second'
    rows=plate.owner_rows(proof,'worker').exact()
    assert state['candidates']==1
    assert state['fields']==[[A,B],[A],[B]]
    assert {r['id']:r['labels'] for r in rows}=={'test-a':['new-a'],'test-b':['new-b']}

def test_membership_change_restarts_candidate_selection(changing):
    proof,state=changing;state['mode']='membership'
    rows=plate.owner_rows(proof,'worker').exact()
    assert state['candidates']==2
    assert state['fields']==[[A,B],[B]]
    assert [r['id'] for r in rows]==['test-b']

def test_store_identity_change_restarts_full_projection(changing):
    proof,state=changing;state['mode']='store'
    rows=plate.owner_rows(proof,'worker').exact()
    assert state['candidates']==2
    assert state['fields']==[[A,B],[A,B]]
    assert next(r for r in rows if r['id']=='test-a')['labels']==['new-a']

def test_unreadable_proof_never_repairs_or_returns_mixed_rows(changing):
    proof,state=changing;state['mode']='malformed'
    assert not plate.owner_rows(proof,'worker').complete
    assert state['fields']==[[A,B]]

def test_continuous_changes_share_one_three_pass_budget(changing):
    proof,state=changing;state['mode']='always'
    assert not plate.owner_rows(proof,'worker').complete
    assert state['candidates']==1
    assert state['fields']==[[A,B],[A],[A]]


def test_membership_change_during_entity_repair_forces_full_restart(changing):
    proof,state=changing;state['mode']='late-membership'
    rows=plate.owner_rows(proof,'worker').exact()
    assert state['candidates']==2
    assert state['fields']==[[A,B],[A],[B]]
    assert [r['id'] for r in rows]==['test-b']

def test_store_replacement_during_repair_restarts_all_rows(changing):
    proof,state=changing;state['mode']='late-store'
    assert len(plate.owner_rows(proof,'worker').exact())==2
    assert state['candidates']==2
    assert state['fields']==[[A,B],[A],[A,B]]

@pytest.mark.parametrize('mode',['epoch','bad-fields'])
def test_invalid_repair_never_reuses_previously_valid_rows(changing,mode):
    proof,state=changing;state['mode']=mode
    assert not plate.owner_rows(proof,'worker').complete
    assert state['candidates']==1
    assert state['fields']==[[A,B],[A]]


def test_elapsed_time_budget_is_shared_with_repairs(changing,monkeypatch):
    proof,state=changing
    clock=[0.0]
    fake=SimpleNamespace(monotonic=lambda:clock[0])
    monkeypatch.setattr(plate,'time',fake)
    monkeypatch.setattr(cache,'time',fake)
    send=plate.urlopen
    def delayed(request,timeout):
        result=send(request,timeout)
        if request.get_method()=='POST' and '?predicate ?value' in json.loads(request.data)['query']:
            clock[0]+=2
        return result
    monkeypatch.setattr(plate,'urlopen',delayed)
    assert not plate.owner_rows(proof,'worker',timeout=1).complete
    assert state['candidates']==1
    assert state['fields']==[[A,B],[A]]


def test_store_restart_drops_render_scoped_shape_admission(changing):
    proof,state=changing;state['mode']='store'
    admission=plate.RenderShapeReads()
    assert admission.check(proof,('worker',),timeout=30)
    assert admission.supported
    assert plate.owner_rows(proof,'worker',shape_reads=admission).exact()
    assert state['candidates']==2
    assert 'unsupported-owner-status' in state['candidate_queries'][1]
    assert not admission.supported  # No old-store positive leaks to later owners.


@pytest.mark.parametrize("size,requests", [(668,1),(1001,2)])
def test_field_projection_batches_one_thousand_subjects(monkeypatch,size,requests):
    selected={plate.SEEDS+'item/test-'+str(i):G for i in range(size)}
    queries=[]
    def query(proof,text,timeout):
        queries.append(text)
        rows=[dict(subject=s,graph=G,predicate=plate.SCHEMA+'identifier',value=s.rsplit('/',1)[1]) for s in selected if '<'+s+'>' in text]
        return dict(rows=rows,count=len(rows),truncated=False)
    monkeypatch.setattr(plate,'_query',query)
    assert set(plate._project_fields(None,selected,(G,),30))==set(selected)
    assert len(queries)==requests
    assert all(sum("<"+subject+">" in text for subject in selected)<=1000 for text in queries)
