"""A changed payload repairs its fields; membership/store changes restart."""
import json
import re
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
import pytest
from shantytown import seeds_plate as plate, seeds_read_cache as cache

G = 'https://example.test/repair'
A, B = [plate.SEEDS + 'item/' + key for key in ('test-a', 'test-b')]
C = plate.SEEDS + 'item/test-c'

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
            if query.lstrip().startswith('ASK'):
                state['schema_checks']=state.get('schema_checks',0)+1
                return Response(dict(result=bool(state.get('legacy_on_replace') and state['store']=='replacement')))
            if '?predicate ?value' not in query:
                state['candidates']+=1
                state.setdefault('candidate_queries',[]).append(query)
                subjects=[B] if state.get('moved') else [A,B]
                if state.get('entered'):subjects.append(C)
                if 'VALUES ?s {' in query:
                    if state.get('bad_scoped'):return Response(dict(rows=[],count=0,truncated=True))
                    scoped=set(re.findall(r'<([^>]+)>', query.split('VALUES ?s {',1)[1].split('}',1)[0]))
                    subjects=[s for s in subjects if s in scoped]
                    if state.get('payload_during_revalidation'):
                        state['tx']+=1;state['labels'][B]='late-b'
                        state['records'].append(dict(tx=state['tx'],graph=G,entity=B,attribute=plate.SCHEMA+'keywords',op='assert'))
                rows=[dict(subject=s, graph=G) for s in subjects]
                if state.get('unsupported'):rows.append(dict(subject=C,problem='unsupported-owner-status'))
            else:
                subjects=[s for s in (A,B,C) if '<'+s+'>' in query]
                state['fields'].append(subjects)
                inverse={v:k for k,v in plate.FIELDS.items()}
                rows=[]
                for subject in subjects:
                    values=dict(id=subject.rsplit('/',1)[1],title='work',status='open',assignee='worker',priority=state.get('priorities',{}).get(subject,1),issue_type='task',labels=state['labels'][subject])
                    if state['mode']=='bad-fields' and len(state['fields'])==2: values['priority']={'unsupported':'bad'}
                    rows.extend(dict(subject=subject,graph=G,predicate=inverse[k],value=v) for k,v in values.items())
                n=len(state['fields']);mode=state['mode']
                if n==1 or mode=='always' or (mode in ('second','late-membership','late-store','epoch') and n==2):
                    subject=B if n==2 and mode in ('second','late-membership','late-store','epoch') else A
                    state['tx']+=1
                    attribute=plate.SCHEMA+'keywords'
                    if state.get('foreign_membership'):
                        subject=C if state.get('foreign_enters') or state.get('foreign_bad_status') else C+'/comment/1';attribute=plate.SCHEMA+'agent'
                        if state.get('foreign_enters'):
                            state['entered']=True;state['labels'][C]='new-c'
                        if state.get('foreign_bad_status'):state['unsupported']=True
                    if subject in state['labels']:state['labels'][subject]='new-'+subject[-1]
                    if state.get('priority_change'):
                        attribute=plate.SEEDS+'ontology/priority'
                        state.setdefault('priorities',{})[subject]=2
                    if mode=='membership' or (mode=='late-membership' and n==2): attribute=plate.SCHEMA+'agent';state['moved']=True
                    if mode=='store' or (mode=='late-store' and n==2): state['store']='replacement';state['records']=[]
                    else: state['records'].append(dict(tx=state['tx'],graph=G,entity=subject,attribute=attribute,op='assert'))
            return Response(dict(rows=rows,count=len(rows),truncated=False))
        q=parse_qs(urlsplit(request.full_url).query);since=int(q['since'][0]);graph=q['graph'][0]
        records=[r.copy() for r in state['records'] if r['graph']==graph and r['tx']>since]
        if state.get('many_foreign') and records:
            records=[dict(record,entity=C+'/comment/'+str(i)) for record in records for i in range(129)]
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


def test_selected_priority_change_repairs_fields_without_candidate_restart(changing):
    proof,state=changing
    state['priority_change']=True
    rows=plate.owner_rows(proof,'worker').exact()
    assert state['candidates']==1
    assert state['fields']==[[A,B],[A]]
    assert {r['id']:r['priority'] for r in rows}=={'test-a':2,'test-b':1}

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
    assert set(plate._project_fields(None,selected,(G,),30,batch_size=1000))==set(selected)
    assert len(queries)==requests
    assert all(sum("<"+subject+">" in text for subject in selected)<=1000 for text in queries)


def test_non_owner_large_field_budget_keeps_existing_small_batches(monkeypatch):
    selected={plate.SEEDS+'item/test-'+str(i):G for i in range(1001)}
    def query(proof,text,timeout):
        rows=[]
        for subject in selected:
            if '<'+subject+'>' not in text:continue
            values=[(plate.SCHEMA+'identifier',subject.rsplit('/',1)[1]),(plate.SCHEMA+'name','work'),(plate.SEEDS+'ontology/status','open')]
            values += [(plate.SCHEMA+'keywords','tag-'+str(i)) for i in range(9)]
            rows.extend(dict(subject=subject,graph=G,predicate=k,value=v) for k,v in values)
        return dict(rows=rows,count=len(rows),truncated=False)
    monkeypatch.setattr(plate,'_query',query)
    assert len(plate._project_fields(None,selected,(G,),30,budget=100000))==1001


def test_store_restart_rechecks_native_schema_not_only_owner_status(changing):
    proof,state=changing
    state.update(mode='store',legacy_on_replace=True)
    answer=plate.owner_rows(proof,'worker')
    assert not answer.complete
    assert state['candidates']==1
    assert state['schema_checks']==1


def test_foreign_membership_revalidates_without_full_hydration(changing):
    proof,state=changing;state['foreign_membership']=True
    rows=plate.owner_rows(proof,'worker').exact()
    assert len(rows)==2
    assert state['fields']==[[A,B]]
    assert state['candidates']==2
    assert 'VALUES ?s {' in state['candidate_queries'][-1]


def test_payload_during_foreign_revalidation_is_repaired_and_refenced(changing):
    proof,state=changing
    state.update(foreign_membership=True,payload_during_revalidation=True)
    rows=plate.owner_rows(proof,'worker').exact()
    assert state['fields']==[[A,B],[B]]
    assert {r['id']:r['labels'] for r in rows}=={'test-a':['old-a'],'test-b':['late-b']}


def test_new_candidate_during_foreign_revalidation_forces_full_restart(changing):
    proof,state=changing;state.update(foreign_membership=True,foreign_enters=True)
    rows=plate.owner_rows(proof,'worker').exact()
    assert {r['id'] for r in rows}=={'test-a','test-b','test-c'}
    assert state['fields']==[[A,B],[A,B,C]]
    assert state['candidates']==3  # Initial, scoped check, complete restart.


def test_foreign_unsupported_status_never_reuses_old_rows(changing):
    proof,state=changing;state.update(foreign_membership=True,foreign_bad_status=True)
    assert not plate.owner_rows(proof,'worker').complete
    assert state['fields']==[[A,B]]


def test_oversized_foreign_membership_set_keeps_complete_restart(changing):
    proof,state=changing;state.update(foreign_membership=True,many_foreign=True)
    assert len(plate.owner_rows(proof,'worker').exact())==2
    assert state['fields']==[[A,B],[A,B]]
    assert all('VALUES ?s {' not in q for q in state['candidate_queries'])


def test_custom_admission_keeps_complete_membership_restart(changing):
    proof,state=changing;state['foreign_membership']=True
    shape=SimpleNamespace(check=lambda *args,**kwargs:True)
    assert len(plate.owner_rows(proof,'worker',shape_reads=shape).exact())==2
    assert state['fields']==[[A,B],[A,B]]
    assert all('VALUES ?s {' not in q for q in state['candidate_queries'])


def test_truncated_scoped_relation_cannot_certify_old_rows(changing):
    proof,state=changing;state.update(foreign_membership=True,bad_scoped=True)
    assert not plate.owner_rows(proof,'worker').complete
    assert state['fields']==[[A,B]]


@pytest.mark.parametrize('allowance,complete', [(3, False), (8, True)])
def test_stopped_owner_408_restarts_with_smaller_fenced_field_batches(changing, monkeypatch, allowance, complete):
    from urllib.error import HTTPError
    proof, state = changing
    state['mode'] = 'quiet'
    send = plate.urlopen
    refused = []
    def bounded(request, timeout):
        if request.get_method() == 'POST':
            query = json.loads(request.data)['query']
            if '?predicate ?value' in query and '<'+A+'>' in query and '<'+B+'>' in query:
                refused.append(timeout)
                raise HTTPError(request.full_url, 408, 'query timeout', {}, None)
        return send(request, timeout)
    monkeypatch.setattr(plate, 'urlopen', bounded)
    answer = plate.owner_rows(proof, None, plate_owners=('worker',), capacity=True,
                              include_deferred=True, recovery_tokens=allowance)
    assert answer.complete is complete
    assert len(refused) == 1
    if complete:
        assert {r['id'] for r in answer.exact()} == {'test-a', 'test-b'}
        assert state['fields'] == [[A], [B], [A]]  # first field changed; repaired under the same fence
        assert state['candidates'] == 2
    else:
        assert not state['fields']


def test_stopped_owner_single_subject_408_remains_unknown(changing, monkeypatch):
    from urllib.error import HTTPError
    proof, state = changing
    send = plate.urlopen
    calls = []
    def unavailable(request, timeout):
        if request.get_method() == 'POST' and '?predicate ?value' in json.loads(request.data)['query']:
            calls.append(timeout)
            raise HTTPError(request.full_url, 408, 'still timed out', {}, None)
        return send(request, timeout)
    monkeypatch.setattr(plate, 'urlopen', unavailable)
    assert not plate.owner_rows(proof, None, plate_owners=('worker',), capacity=True,
                                include_deferred=True, recovery_tokens=8).complete
    assert len(calls) == 2  # two subjects -> one subject -> refuse; never omit a timed-out subject
