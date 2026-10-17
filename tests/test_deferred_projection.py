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
        assert len(calls)==7
        assert G+'#seeds-ephemeral' in calls[-1]

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
 assert rows[0]['status']=='open' and any('CONTAINS(?askNotes, "steve_quote:")' in q for q in calls)
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

@pytest.mark.parametrize('target_status,expected', [('blocked', 1), ('open', 0), ('closed', 0), (None, 0)])
def test_status_only_blocked_waiter_native_tend_once_across_restart(monkeypatch, tmp_path, target_status, expected):
    from datetime import datetime, timezone
    from shantytown import notify, feed_check
    now = datetime(2026, 10, 13, 16, tzinfo=timezone.utc)
    tracker = SdTracker(quipu=PROOF.quipu_url, prefix='test')
    monkeypatch.setattr(tracker, 'prove_store', lambda: PROOF)
    monkeypatch.setattr(tracker, '_use_remote_projection', lambda: True)
    monkeypatch.setattr(tracker, '_bd', lambda *a: pytest.fail('SDK fallback escaped'))
    target = seeds_plate.SEEDS + 'item/test-two'
    candidate_queries = []
    def query(proof, q, timeout):
        is_target = target in q
        if 'AS ?predicate' in q:
            if is_target:
                fields = wire(id='test-two', status=target_status, notes='repo: same', updated_at=now.isoformat())
                for field in fields:
                    field['subject'] = target
            else:
                fields = wire(status='blocked', notes='repo: same\nresume_when: closed:test-two')
            return dict(rows=fields, count=len(fields), truncated=False)
        if not is_target:
            candidate_queries.append(q)
            assert ' UNION ' not in q
        found = [] if is_target and target_status is None else [dict(subject=target if is_target else S, graph=G)]
        return dict(rows=found, count=len(found), truncated=False)
    monkeypatch.setattr(seeds_plate, '_query', query)
    monkeypatch.setattr(feed_check, 'backend_adapter', lambda *a: tracker)
    candidates = tracker.backstop_rows().exact()
    assert candidates[0]['status'] == 'blocked'
    assert candidates[0]['labels'] == [] and candidates[0]['defer_until'] is None
    calls = []
    for _ in range(3):
        alert = notify.DeferralAlerter(tmp_path, None, None, now=now,
                                     push=lambda *a: calls.append(a[-1]) or 'sattler')
        alert.sweep()
    assert len(calls) == expected
    if expected:
        assert 'test-one -> test-two' in calls[0] and 'gate target is deferred/blocked' in calls[0]
    assert len(candidate_queries) == 4 * 16
    assert any('"blocked"' in q and 'CONTAINS(?gateNotes, "resume_when:")' in q
               for q in candidate_queries)


def test_a_typed_due_date_is_read_not_refused(monkeypatch):
    """aegis-qc2, measured 2026-10-16: every item with an ical:due (typed
    xsd:dateTime) made the deferral read refuse, so the sweep never summarized."""
    typed = {'datatype': 'http://www.w3.org/2001/XMLSchema#dateTime',
             'value': '2026-10-30T05:30:08Z'}
    answer, _ = project(monkeypatch, wire(due_at=typed))
    assert answer.exact()[0]['due_at'] == '2026-10-30T05:30:08Z'


def test_other_typed_fields_still_refuse_and_name_the_field(monkeypatch):
    typed = {'datatype': 'http://www.w3.org/2001/XMLSchema#string', 'value': 'held'}
    answer, _ = project(monkeypatch, wire(title=typed))
    with pytest.raises(PartialAnswer, match='unsupported typed deferral field: title'):
        answer.exact()


def test_backstop_splits_candidate_union_without_losing_classes(monkeypatch):
    """The measured 16-arm candidate times out; each unchanged arm completes."""
    candidates = []
    hydrated = []
    def query(proof, q, timeout):
        if 'AS ?predicate' in q:
            hydrated.append(q)
            return dict(rows=wire(), count=len(wire()), truncated=False)
        if ' UNION ' in q:
            raise ValueError('measured candidate UNION execution budget')
        candidates.append(q)
        # A deferred item can also have several dates/notes: duplicate matches
        # retain a single hydrated item, with both graphs still interrogated.
        return dict(rows=[dict(subject=S, graph=G)], count=1, truncated=False)
    monkeypatch.setattr(seeds_plate, '_query', query)
    assert seeds_plate.deferred_rows(PROOF, include_asks=True).exact()[0]['id'] == 'test-one'
    assert len(candidates) == 16 and len(hydrated) == 1
    assert all(len(q.encode()) < 700 for q in candidates)
    for graph in (G, G + '#seeds-ephemeral'):
        scoped = [q for q in candidates if f'GRAPH <{graph}>' in q]
        assert len(scoped) == 8
        assert any('"deferred"' in q for q in scoped)
        for predicate in ('scheduledTime', 'deferUntil'):
            assert any('"open"' in q and predicate in q for q in scoped)
        for status in ('open', 'blocked', 'in_progress'):
            assert any(f'"{status}"' in q and 'steve_quote:' in q for q in scoped)
        for status in ('open', 'blocked'):
            assert any(f'"{status}"' in q and 'resume_when:' in q for q in scoped)


@pytest.mark.parametrize('failure', ['late-error', 'total-budget', 'cross-chunk-shadow'])
def test_split_candidates_refuse_whole_read_before_hydration(monkeypatch, failure):
    calls = []
    def query(proof, q, timeout):
        assert 'AS ?predicate' not in q, 'partial candidate set was hydrated'
        calls.append(q)
        if failure == 'late-error' and len(calls) == 6:
            raise ValueError('late branch timeout')
        row = dict(subject=S, graph=G)
        if failure == 'cross-chunk-shadow' and len(calls) == 2:
            row['graph'] = G + '#seeds-ephemeral'
        rows = [row] * (5000 if failure == 'total-budget' else 1)
        return dict(rows=rows, count=len(rows), truncated=False)
    monkeypatch.setattr(seeds_plate, '_query', query)
    with pytest.raises(PartialAnswer):
        seeds_plate.deferred_rows(PROOF).exact()
    assert len(calls) >= 2


def test_split_candidates_share_one_wall_budget(monkeypatch):
    ticks = iter([0, 0, 31])
    monkeypatch.setattr(seeds_plate.time, 'monotonic', lambda: next(ticks))
    calls = []
    def query(proof, q, timeout):
        calls.append(timeout)
        return dict(rows=[], count=0, truncated=False)
    monkeypatch.setattr(seeds_plate, '_query', query)
    with pytest.raises(PartialAnswer, match='candidate time budget'):
        seeds_plate.deferred_rows(PROOF, timeout=30).exact()
    assert calls == [30]


def test_split_candidate_set_equals_union_on_real_graphs(monkeypatch):
    rdf = pytest.importorskip('rdflib', minversion='7.1')
    dataset = rdf.Dataset()
    expected = set()
    for graph in (G, G + '#seeds-ephemeral'):
        store = dataset.graph(rdf.URIRef(graph))
        cases = [('deferred', None, None),
                 ('open', seeds_plate.SCHEMA + 'scheduledTime', None),
                 ('open', seeds_plate.SEEDS + 'ontology/deferUntil', None)]
        cases += [(status, None, marker) for marker, statuses in (
            ('steve_quote:', ('open', 'blocked', 'in_progress')),
            ('resume_when:', ('open', 'blocked'))) for status in statuses]
        for i, (status, date, marker) in enumerate(cases):
            subject = rdf.URIRef(S + str(len(expected)))
            expected.add((str(subject), graph))
            store.add((subject, rdf.RDF.type, rdf.URIRef(seeds_plate.SCHEMA + 'Action')))
            store.add((subject, rdf.URIRef(seeds_plate.SEEDS + 'ontology/status'), rdf.Literal(status)))
            if date:
                store.add((subject, rdf.URIRef(date), rdf.Literal('2026-10-18')))
            if marker:
                store.add((subject, rdf.URIRef(seeds_plate.SEEDS + 'ontology/notes'), rdf.Literal(marker + ' yes')))
        # A closed note and a plain open row must not enter the candidate set.
        for status in ('closed', 'open'):
            subject = rdf.URIRef(S + status)
            store.add((subject, rdf.RDF.type, rdf.URIRef(seeds_plate.SCHEMA + 'Action')))
            store.add((subject, rdf.URIRef(seeds_plate.SEEDS + 'ontology/status'), rdf.Literal(status)))
            if status == 'closed':
                store.add((subject, rdf.URIRef(seeds_plate.SEEDS + 'ontology/notes'), rdf.Literal('steve_quote: no')))
    queries, found = [], set()
    def query(proof, q, timeout):
        if 'AS ?predicate' in q:
            raise ValueError('stop after complete candidate acquisition')
        queries.append(q)
        rows = [dict(subject=str(row.subject), graph=str(row.graph)) for row in dataset.query(q)]
        found.update((row['subject'], row['graph']) for row in rows)
        return dict(rows=rows, count=len(rows), truncated=False)
    monkeypatch.setattr(seeds_plate, '_query', query)
    with pytest.raises(PartialAnswer):
        seeds_plate.deferred_rows(PROOF, include_asks=True).exact()
    assert len(queries) == 16 and found == expected
    arms = [q.split(' WHERE { ', 1)[1].rsplit(' } LIMIT ', 1)[0] for q in queries]
    original = 'SELECT (STR(?s) AS ?subject) ?graph WHERE { ' + ' UNION '.join(arms) + ' } LIMIT 10000'
    union = {(str(row.subject), str(row.graph)) for row in dataset.query(original)}
    assert union == found == expected
