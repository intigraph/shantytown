"""Short source/CI gates are WIP, while a genuinely empty plate stays feedable."""
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from shantytown import busy_wait, feed_check, runtime, session_budget, stop_policy
from shantytown.files import FilesRegistry
from shantytown.protocols import Agent
from shantytown.tmux import NullPanes

NOW = datetime(2026, 10, 15, 17, 35, tzinfo=timezone.utc)


def row(identifier='task-1', **kw):
    value = dict(id=identifier, title='source acceptance', assignee='worker',
                 status='deferred', priority=2, labels=[],
                 defer_until=(NOW+timedelta(minutes=10)).isoformat())
    value.update(kw)
    return value


def test_all_eight_near_gates_occupy_worker_and_empty_plate_is_control():
    values = [row('task-'+str(i)) for i in range(8)]
    assert busy_wait.from_rows(values, ['worker'], now=NOW) == {'worker'}
    assert busy_wait.from_rows([], ['worker'], now=NOW) == set()


@pytest.mark.parametrize('minutes,waiting', [(-61,False),(-60,True),(-1,True),
                                           (0,True),(60,True),(61,False),(1440,False)])
def test_bounded_future_and_elapsed_grace(minutes, waiting):
    value = row(defer_until=(NOW+timedelta(minutes=minutes)).isoformat())
    assert bool(busy_wait.from_rows([value], ['worker'], now=NOW)) is waiting


@pytest.mark.parametrize('status', ['open','hooked','in_progress'])
def test_available_own_work_must_not_be_starved_by_another_ci_gate(status):
    values = [row(), row('own-2', status=status, defer_until=None)]
    assert busy_wait.from_rows(values, ['worker'], now=NOW) == set()


@pytest.mark.parametrize('change', [dict(status='closed'),dict(title='inbox: notice'),
                                   dict(labels=['anchor']),dict(labels=['decision-needed'])])
def test_closed_messages_anchors_and_decisions_do_not_occupy_capacity(change):
    assert busy_wait.from_rows([row(**change)], ['worker'], now=NOW) == set()


@pytest.mark.parametrize('value', [True,'not-a-date','2026-10-15T17:45:00'])
def test_ambiguous_dates_are_unknown_not_spare_capacity(value):
    with pytest.raises(ValueError):
        busy_wait.from_rows([row(defer_until=value)], ['worker'], now=NOW)


def test_long_hold_and_undated_defer_do_not_hide_worker_forever():
    assert busy_wait.from_rows([row(defer_until=None)], ['worker'], now=NOW) == set()
    assert busy_wait.from_rows([row(defer_until='2027-01-01')], ['worker'], now=NOW) == set()


def world(tmp_path, monkeypatch, values):
    (tmp_path/'shantytown.toml').write_text('[env]\nSHANTY_BACKEND="files"\n')
    items=tmp_path/'items'
    items.mkdir()
    for value in values:
        (items/(value['id']+'.json')).write_text(json.dumps(value))
    reg=FilesRegistry(tmp_path/'crew')
    reg.set(Agent(name='worker',role='worker',pane='p'))
    panes=NullPanes(live={'p'},screen='> \n? for shortcuts')
    monkeypatch.setattr(feed_check,'st_launched_agents',lambda _:None)
    monkeypatch.setattr(feed_check,'dark_agents',lambda:set())
    monkeypatch.setattr(runtime,'live_wiring',lambda *a:SimpleNamespace(directions={'send'}))
    monkeypatch.setattr(session_budget,'at_ceiling',lambda *a:None)
    monkeypatch.setattr(busy_wait,'utc_now',lambda:NOW)
    monkeypatch.setattr(feed_check,'queue_state',lambda *a,**k:(
        [{'id':'pool-1','title':'new work','status':'open','priority':2}],[]))
    return reg,panes,runtime.ClaudeRuntime(panes,lambda *a:None)


def verdict(root, reg, panes, program):
    free,ready,_=feed_check.gate_inputs(root,reg,panes,program,admits=lambda *a:'')
    return stop_policy.decide(stop_policy.Inputs(
        me='coordinator',role='administrator',free_feedable=free,dispatchable=ready))


def test_actual_shared_stop_and_tend_selector_on_selected_files(tmp_path,monkeypatch):
    reg,panes,program=world(tmp_path,monkeypatch,[row()])
    assert feed_check.free_feedable_workers(reg,panes,program,tmp_path) == []
    assert not verdict(tmp_path,reg,panes,program).block
    for path in (tmp_path/'items').glob('*.json'):
        path.unlink()
    assert feed_check.free_feedable_workers(reg,panes,program,tmp_path) == ['worker']
    assert verdict(tmp_path,reg,panes,program).by == stop_policy.BY_RULE_ZERO
    assert panes.exists('p')


def test_failed_waiting_read_cannot_prove_free(tmp_path,monkeypatch,capsys):
    reg,panes,program=world(tmp_path,monkeypatch,[])
    def failed(*a,**k): raise TimeoutError
    monkeypatch.setattr(busy_wait,'rows',failed)
    assert feed_check.free_feedable_workers(reg,panes,program,tmp_path) == []
    assert not verdict(tmp_path,reg,panes,program).block
    assert 'occupancy UNKNOWN' in capsys.readouterr().err


def test_only_requested_owners_count_and_scope_mismatch_refuses():
    assert busy_wait.from_rows([row(assignee='crew/worker')],['worker'],now=NOW)=={'worker'}
    with pytest.raises(ValueError):
        busy_wait.from_rows([row(assignee='other')],['worker'],now=NOW)


def test_native_owner_batch_includes_deferred_metadata_without_hydration(tmp_path,monkeypatch):
    from shantytown import seeds_plate
    from shantytown.sd import SdTracker
    from test_seeds_plate_projection import PROOF,G,fields,answer
    (tmp_path/'shantytown.toml').write_text('[env]\nSHANTY_BACKEND="seeds"\n')
    tracker=SdTracker(quipu=PROOF.quipu_url,prefix='test')
    monkeypatch.setattr(tracker,'_use_remote_projection',lambda:True)
    monkeypatch.setattr(tracker,'prove_store',lambda:PROOF)
    monkeypatch.setattr(tracker,'_bd',lambda *a:pytest.fail('SDK hydration'))
    monkeypatch.setattr(feed_check,'_br_tracker',lambda *a:tracker)
    monkeypatch.setattr(seeds_plate,'owner_shape_supported',lambda *a,**k:True)
    queries=[]
    def query(proof,text,timeout):
        queries.append(text)
        if '?predicate ?value WHERE' in text:
            return answer(fields('test-wait',status='deferred',
                                 defer_until={'datatype':'http://www.w3.org/2001/XMLSchema#dateTime',
                                              'value':row()['defer_until']}))
        return answer([{'subject':seeds_plate.SEEDS+'item/test-wait','graph':G}])
    monkeypatch.setattr(seeds_plate,'_query',query)
    got=busy_wait.rows(tmp_path,None,['worker'])
    assert busy_wait.from_rows(got,['worker'],now=NOW)=={'worker'}
    assert len(queries)==2 and '"deferred"' in queries[0]
    assert seeds_plate._feed_owner_clause(('worker',)) in queries[0]
    assert all('description' not in q and 'ontology/notes' not in q for q in queries)


def test_native_waiting_projection_refuses_unscoped_read(monkeypatch):
    from shantytown import seeds_plate
    from test_seeds_plate_projection import PROOF
    monkeypatch.setattr(seeds_plate,'_query',lambda *a,**k:pytest.fail('unscoped query'))
    result=seeds_plate.owner_rows(PROOF,None,include_deferred=True)
    assert not result.complete


@pytest.mark.parametrize('owner', ['', 'foreign'])
def test_waiting_projection_refuses_unrequested_wire_owner(monkeypatch, owner):
    from shantytown import seeds_plate
    from test_seeds_plate_projection import PROOF, fields, answer
    monkeypatch.setattr(seeds_plate, 'owner_shape_supported', lambda *a, **k:True)
    monkeypatch.setattr(seeds_plate, '_query', lambda *a:answer(fields(assignee=owner)))
    assert not seeds_plate.owner_rows(PROOF, None, plate_owners=('worker',),
                                     capacity=True, include_deferred=True).complete


def test_actual_rdf_projection_includes_both_graphs_and_excludes_other_owners(monkeypatch):
    from rdflib import Dataset, URIRef, Literal, RDF, XSD
    from shantytown import seeds_plate
    from test_seeds_plate_projection import PROOF, G, answer

    data = Dataset()
    inverse = {value: key for key, value in seeds_plate.FIELDS.items()}
    for identifier, graph, owner, status in (
        ('test-shared', G, 'worker', 'deferred'),
        ('test-ephemeral', G+'#seeds-ephemeral', 'crew/worker', 'blocked'),
        ('test-foreign', G, 'other', 'deferred'),
        ('test-closed', G, 'worker', 'closed'),
    ):
        subject = URIRef(seeds_plate.SEEDS+'item/'+identifier)
        target = data.graph(URIRef(graph))
        target.add((subject, RDF.type, URIRef(seeds_plate.SCHEMA+'Action')))
        for key, value in row(identifier, assignee=owner, status=status).items():
            literal = (Literal(value, datatype=XSD.dateTime) if key == 'defer_until'
                       else Literal(value))
            if key != 'labels':
                target.add((subject, URIRef(inverse[key]), literal))

    def query(_proof, text, timeout):
        if text.startswith('ASK '):
            return {'result':bool(data.query(text))}
        return answer([
            {str(key): ({'value':str(value), 'datatype':str(value.datatype)}
                        if isinstance(value, Literal) and value.datatype == XSD.dateTime
                        else value.toPython() if isinstance(value, Literal) else str(value))
             for key, value in result.asdict().items()}
            for result in data.query(text)
        ])

    monkeypatch.setattr(seeds_plate, '_query', query)
    try:
        result = seeds_plate.owner_rows(PROOF, None, plate_owners=('worker',),
                                       capacity=True, include_deferred=True).exact()
        assert {value['id'] for value in result} == {'test-shared', 'test-ephemeral'}
        assert busy_wait.from_rows(result, ['worker'], now=NOW) == {'worker'}
    finally:
        data.close()
