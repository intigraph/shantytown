"""Operation records belong to their phase-CAS runner, never ordinary claims."""
import copy
import json
from types import SimpleNamespace

import pytest

from shantytown.feed_check import dispatchable, hauls
from shantytown.stop_event import _assigned_to
from test_lead_haul_feed_by_tend import _lead_hauling_world


@pytest.mark.parametrize('marker', [
    {'labels': ['deploy-operation']},
    {'agent_context': json.dumps({'deploy_admission': {'phase': 'prepared'}})},
    {'agent_context': {'deploy_admission': {}}},
    {'agent_context': '{broken'},
])
@pytest.mark.parametrize('status', ['open', 'in_progress'])
def test_operation_never_enters_a_haul_or_dispatch_pool(marker, status):
    operation = dict(id='op-1', title='Prepared rollout', assignee='worker', status=status, **marker)
    before = copy.deepcopy(operation)
    assert hauls([operation]) == {}
    assert _assigned_to('worker', [operation]) == []
    assert dispatchable([], [dict(operation, assignee='')]) == []
    assert operation == before


@pytest.mark.parametrize('marker', [
    {'labels': ['deploy-operation']},
    {'agent_context': json.dumps({'deploy_admission': {'phase': 'prepared'}})},
])
def test_natural_feed_does_not_claim_send_or_preflight_operation(tmp_path, monkeypatch, marker):
    claims = []
    alerter, panes = _lead_hauling_world(tmp_path, monkeypatch, claims)
    row = dict(id='op-1', title='Prepared rollout', assignee='dearing', **marker)
    before = copy.deepcopy(row)
    alerter._bd_ready = lambda: [row]
    inputs = []
    alerter._input_preflight = lambda who: inputs.append(who) or SimpleNamespace(verdict='empty', detail='test')
    alerter.sweep([])
    assert claims == []
    assert panes.sent == []
    assert inputs == []
    assert row == before


def test_ordinary_work_with_context_is_still_feedable():
    row = dict(id='work-1', title='Repair rollout docs', assignee='worker',
               agent_context=json.dumps({'instructions': 'ordinary work'}))
    assert hauls([row]) == {'worker': ['work-1']}
    assert _assigned_to('worker', [row]) == [row]
    assert dispatchable([], [dict(row, assignee='')]) == [('work-1', 'Repair rollout docs')]


@pytest.mark.parametrize('marker', [
    {'labels': ['deploy-operation']},
    {'agent_context': json.dumps({'deploy_admission': {}})},
])
def test_exact_claim_refuses_operation_before_any_write(monkeypatch, marker):
    from shantytown import br
    writes = []
    tracker = SimpleNamespace(repo='store', _bd=lambda *a: writes.append(a))
    monkeypatch.setattr(br, '_owning_store', lambda *a: ('store', dict(id='op-1', **marker)))
    with pytest.raises(RuntimeError, match='phase-CAS'):
        br.claim(tracker, 'op-1')
    assert writes == []


def test_stale_ordinary_projection_cannot_send_after_exact_operation_refusal(tmp_path, monkeypatch):
    from shantytown import feed_check
    from shantytown.inbox import OperationClaimRefused
    claims = []
    alerter, panes = _lead_hauling_world(tmp_path, monkeypatch, claims)
    def exact_claim(*args, **kwargs):
        claims.append(args[1])
        raise OperationClaimRefused('exact read now identifies a deployment operation')
    monkeypatch.setattr(feed_check, 'bd_claim', exact_claim)
    alerter.sweep([])
    assert claims == ['aegis-2b2tti']
    assert panes.sent == []


@pytest.mark.parametrize('wire', [
    '[{"id":"op-1","labels":["deploy-operation"]}]',
    '{broken',
    '[]',
])
def test_legacy_direct_claim_refuses_operation_or_unknown(monkeypatch, wire):
    from shantytown import feed_check
    from shantytown.inbox import OperationClaimRefused
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout=wire)
    monkeypatch.setattr(feed_check.subprocess, 'run', run)
    with pytest.raises(OperationClaimRefused):
        feed_check.bd_claim(None, 'op-1')
    assert len(calls) == 1 and calls[0][1] == 'show'
