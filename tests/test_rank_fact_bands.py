from datetime import datetime,timezone,timedelta
from types import SimpleNamespace as NS

import pytest
from shantytown import board_rank as rank, seeds_plate

NOW=datetime(2026,11,4,13,tzinfo=timezone.utc)
POLICIES={kind:dict(iri='urn:rule:'+kind) for kind in rank.KINDS}


def row(i='task',**changes):
    value=dict(id=i,title='ordinary work',priority=1,status='open',assignee='worker',labels=[],blocked_by=[])
    value.update(changes);return value


def proposal(r):return rank.propose([r],POLICIES,{'worker':'up'},now=NOW)['proposals'][0]


def test_stale_external_label_does_not_decide_band_or_release_hold():
    r=row(status='deferred',labels=['blocked:external'],due_at=(NOW+timedelta(days=2)).isoformat())
    result=rank.propose([r],POLICIES,{},now=NOW);p=result['proposals'][0]
    assert p['band']=='due' and p['stale_gate'] is True and p['open_blocker_count']==0
    assert any(c['rule']=='stale-gate' for c in p['citations'])
    assert r['status']=='deferred' and result['undefer_proposed'] is False and result['changes_applied'] is False


@pytest.mark.parametrize('label',['blocked:human','blocked:needs-stiwi','desk','needs-stiwi'])
def test_explicit_gate_stays_blocked_with_zero_edges(label):
    assert proposal(row(labels=[label],open_blockers=[]))['band']=='blocked'


def test_positive_blocker_count_is_blocked_even_without_label():
    assert proposal(row(open_blockers=['outside']))['band']=='blocked'


def test_closed_endpoint_does_not_count_as_open_and_unknown_does_not_mean_zero():
    assert proposal(row(priority=3,blocked_by=['closed'],open_blockers=[]))['band']=='later'
    p=proposal(row(blocked_by=['unreadable'],labels=['blocked:external']))
    assert p['band']=='unknown' and p['open_blocker_count'] is None and p['stale_gate'] is False


@pytest.mark.parametrize('priority,days,expected',[(0,-1,'immediate'),(1,-1,'due'),(2,7,'due'),
                                                (2,8,'normal'),(3,8,'later'),(4,8,'later')])
def test_priority_and_due_facts_define_urgency(priority,days,expected):
    assert proposal(row(priority=priority,due_at=(NOW+timedelta(days=days)).isoformat()))['band']==expected


def test_proven_prerequisite_of_p0_is_immediate():
    prerequisite=row('prerequisite',priority=1)
    parent=row('parent',priority=0,blocked_by=['prerequisite'])
    result=rank.propose([parent,prerequisite],POLICIES,{},now=NOW)
    found={p['item']:p for p in result['proposals']}
    assert found['prerequisite']['proposed_priority']==0 and found['prerequisite']['band']=='immediate'
    assert found['parent']['band']=='blocked'


def test_batch_projection_proves_external_closed_vs_open_status(monkeypatch):
    proof=NS(graph='urn:board',quipu_url='http://example.invalid')
    tracker=NS(prove_store=lambda:proof,timeout=2)
    queries=[]
    def read(_,query,timeout):
        queries.append(query)
        if '?dep' in query:
            return {'rows':[dict(s='https://seeds.local/item/a',id='a',status='open',graph='urn:board',dep='https://seeds.local/item/b')]}
        return {'rows':[dict(s='https://seeds.local/item/b',id='b',status='closed',graph='urn:board')]}
    monkeypatch.setattr(seeds_plate,'_query',read)
    result=rank.dependencies(tracker,[row('a')])
    assert len(queries)==2 and all('VALUES ?s' in q for q in queries)
    assert result[0]['blocked_by']==['b'] and result[0]['open_blockers']==[]


def test_batch_projection_missing_endpoint_refuses_no_zero_assumption(monkeypatch):
    tracker=NS(prove_store=lambda:NS(graph='urn:board',quipu_url='http://example.invalid'),timeout=2)
    def read(_,query,timeout):
        return {'rows':[dict(s='https://seeds.local/item/a',id='a',status='open',graph='urn:board',dep='https://seeds.local/item/b')]} if '?dep' in query else {'rows':[]}
    monkeypatch.setattr(seeds_plate,'_query',read)
    with pytest.raises(rank.TriageError,match='no zero-blocker assumption'):
        rank.dependencies(tracker,[row('a')])


@pytest.mark.parametrize('value',[None,True,-1,'0',{}])
def test_malformed_blocker_count_never_becomes_zero(value):
    p=proposal(row(open_blockers=value,labels=['blocked:external']))
    assert p['band']=='unknown' and p['stale_gate'] is False


def test_stale_label_and_zero_count_are_visible_in_table():
    out=rank.propose([row(labels=['blocked:external'])],POLICIES,{},now=NOW)
    assert 'blocked:external (open blockers=0)' in rank.table(out)


@pytest.mark.parametrize('status',['open','deferred'])
def test_p0_behind_proven_stale_gate_is_immediate(status):
    p=proposal(row(priority=0,status=status,labels=['blocked:bead'],open_blockers=[]))
    assert p['band']=='immediate' and p['stale_gate'] is True


def test_stale_p0_never_overrides_real_human_or_open_dependency_gate():
    assert proposal(row(priority=0,labels=['blocked:external','needs-stiwi'],open_blockers=[]))['band']=='blocked'
    assert proposal(row(priority=0,labels=['blocked:bead'],open_blockers=['real']))['band']=='blocked'


def test_parked_is_later_only_with_proven_zero_blockers():
    assert proposal(row(priority=0,labels=['parked:by-design'],open_blockers=[]))['band']=='later'
    assert proposal(row(labels=['parked:by-design'],open_blockers=['real']))['band']=='blocked'
    assert proposal(row(labels=['parked:by-design'],blocked_by=['unreadable']))['band']=='unknown'


def test_stale_p0_rule_also_covers_future_due_without_item_exceptions():
    p=proposal(row(priority=0,status='deferred',labels=['blocked:bead'],open_blockers=[],
                   due_at=(NOW+timedelta(days=3)).isoformat()))
    assert p['band']=='immediate'
