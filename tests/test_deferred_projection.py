"""Deferral candidates stay complete or UNKNOWN without SDK hydration."""
import pytest
from shantytown import seeds_plate
from shantytown.answer import PartialAnswer
from shantytown.sd import SdTracker, StoreProof

G = 'https://example.test/graph'
PROOF = StoreProof('--quipu', None, 'https://example.test', 'test', G)
S = seeds_plate.SEEDS + 'item/test-one'

def wire(**overrides):
    row = dict(id='test-one', title='held', status='deferred', priority=1,
               created_at='2026-10-01T00:00:00Z', notes='resume_when: closed:test-two')
    row.update(overrides)
    fields = {**seeds_plate.FIELDS, seeds_plate.SEEDS + 'ontology/notes': 'notes'}
    inverse = {v: k for k, v in fields.items()}
    return [dict(subject=S, graph=G, predicate=inverse[k], value=v)
            for k, v in row.items() if v is not None]

def project(monkeypatch, fields, candidates=None):
    calls=[]
    def query(proof, q, timeout):
        calls.append(q)
        assert '?s ?p ?o' not in q and 'FILTER(?p' not in q
        rows = fields if 'AS ?predicate' in q else candidates or [dict(subject=S, graph=G)]
        return dict(rows=rows, count=len(rows), truncated=False)
    monkeypatch.setattr(seeds_plate, '_query', query)
    return seeds_plate.deferred_rows(PROOF), calls

def test_condition_notes_and_dated_open_preserved(monkeypatch):
    for status in ('deferred', 'open'):
        answer, calls = project(monkeypatch, wire(status=status, defer_until='2026-10-11T00:00:00Z'))
        row=answer.exact()[0]
        assert row['notes']=='resume_when: closed:test-two'
        assert row['status']==status and row['defer_until']=='2026-10-11T00:00:00Z'
        assert len(calls)==2
        assert G+'#seeds-ephemeral' in calls[1]

@pytest.mark.parametrize('changed', [dict(status='closed'), dict(status='open'),
                                    dict(priority=True), dict(notes=5), dict(created_at=None)])
def test_invalid_or_changed_candidates_unknown(monkeypatch, changed):
    answer,_=project(monkeypatch, wire(**changed))
    with pytest.raises(PartialAnswer): answer.exact()

@pytest.mark.parametrize('where', ['candidate', 'field', 'duplicate'])
def test_shadow_or_ambiguous_note_unknown(monkeypatch, where):
    fields=wire(); candidates=[dict(subject=S, graph=G)]
    if where=='candidate': candidates.append(dict(subject=S, graph=G+'#seeds-ephemeral'))
    elif where=='field': fields.append(dict(fields[0], graph=G+'#seeds-ephemeral'))
    else: fields.append(dict(fields[-1], value='resume_when: closed:test-other'))
    answer,_=project(monkeypatch,fields,candidates)
    with pytest.raises(PartialAnswer): answer.exact()

def test_native_failure_never_falls_back(monkeypatch):
    tracker=SdTracker(quipu=PROOF.quipu_url,prefix='test')
    monkeypatch.setattr(tracker,'prove_store',lambda:PROOF)
    monkeypatch.setattr(tracker,'_use_remote_projection',lambda:True)
    calls=[]
    def fail(*args): calls.append(args); raise ValueError('unreadable')
    monkeypatch.setattr(seeds_plate,'_query',fail)
    monkeypatch.setattr(tracker,'_bd',lambda *args:pytest.fail('SDK fallback escaped'))
    with pytest.raises(PartialAnswer):tracker.deferred_rows().exact()
    assert len(calls)==1

def test_empty_success_and_native_adapter(monkeypatch):
    tracker=SdTracker(quipu=PROOF.quipu_url,prefix='test')
    monkeypatch.setattr(tracker,'prove_store',lambda:PROOF)
    monkeypatch.setattr(tracker,'_use_remote_projection',lambda:True)
    monkeypatch.setattr(seeds_plate,'_query',lambda *a:dict(rows=[],count=0,truncated=False))
    monkeypatch.setattr(tracker,'_bd',lambda *a:pytest.fail('hydration escaped'))
    assert tracker.deferred_rows().exact()==[]
def test_original_ask_candidates_are_scoped_without_description(monkeypatch):
 calls=[]
 def query(proof,q,timeout):
  calls.append(q)
  return dict(rows=wire(status='open',notes='steve_quote: Data\nsteve_ask_at: 2026-10-05T12:00:00Z\nsteve_source: original') if 'AS ?predicate' in q else [dict(subject=S,graph=G)])
 monkeypatch.setattr(seeds_plate,'_query',query)
 rows=seeds_plate.deferred_rows(PROOF,include_asks=True).exact()
 assert rows[0]['status']=='open' and 'CONTAINS(?askNotes, "steve_quote:")' in calls[0]
 assert all('description' not in q and '?s ?p ?o' not in q for q in calls)
def test_gate_target_metadata_closed_and_batch_bound(monkeypatch):
 calls=[]
 def query(proof,q,timeout):
  calls.append(q)
  return dict(rows=wire(status='closed') if 'AS ?predicate' in q else [dict(subject=S,graph=G)])
 monkeypatch.setattr(seeds_plate,'_query',query)
 assert seeds_plate.deferred_rows(PROOF,target_ids=['test-one']).exact()[0]['status']=='closed'
 assert S in calls[0] and '"deferred"' not in calls[0]
 with pytest.raises(PartialAnswer):seeds_plate.deferred_rows(PROOF,target_ids=['x']*26).exact()
 assert len(calls)==2
