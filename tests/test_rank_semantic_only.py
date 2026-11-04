from datetime import datetime, timezone

import pytest
from shantytown import board_rank as rank, cli

NOW = datetime(2026, 11, 4, 13, tzinfo=timezone.utc)
POLICIES = {kind: dict(iri='urn:rule:' + kind) for kind in rank.KINDS}


def row(i='task', priority=1, status='open', owner=None):
    return dict(id=i, title='routine work', description='No stated personal need',
                priority=priority, status=status, assignee=owner, labels=[], blocked_by=[])


class NoulsOnly:
    def __init__(self): self.calls=[]
    def call(self, tool, arguments):
        assert tool == 'jev_noul', 'rank choice is outside this benchmark authority'
        self.calls.append((tool, arguments))
        return dict(request={'fixture': len(self.calls)}, model='fixture-model', usage={}, answer={'noul': .25})


def cases():
    return [dict(before=row('case' + str(i), priority=i % 4), context=[],
                 source='urn:independent-label:' + str(i), rules=['urn:label:reason'],
                 observed_at=NOW.isoformat(), owner_states={}, owner_evidence='urn:frozen-owner-proof',
                 expected=dict(reowner=None, flags={'automation': i % 2 == 0, 'personal-need': False}))
            for i in range(30)]


@pytest.mark.parametrize('priority,status,owner,expected', [
    (0, 'open', None, True), (1, 'in_progress', '', True),
    (2, 'open', None, False), (3, 'open', None, False),
    (0, 'deferred', None, False), (1, 'blocked', None, False),
    (1, 'open', 'unknown', False), (1, 'open', 'held', False),
])
def test_needs_owner_is_exact_deterministic_scope(priority,status,owner,expected):
    result=rank.propose([row(priority=priority,status=status,owner=owner)],POLICIES,{},now=NOW)
    p=result['proposals'][0]
    assert p['needs_owner'] is expected
    assert p['reowner'] is False
    if expected:
        assert any(c['rule']=='owner-assignment' for c in p['citations'])
    assert result['changes_applied'] is False and result['undefer_proposed'] is False


def test_known_down_owner_still_needs_owner_without_unassigned_rule():
    p=rank.propose([row(owner='worker',priority=3)],POLICIES,{'worker':'down'},now=NOW)['proposals'][0]
    assert p['reowner'] is True and p['needs_owner'] is True


def test_semantic_only_benchmark_cannot_call_rank_even_for_unranked_p0():
    client=NoulsOnly();stored=[]
    output=rank.semantic_benchmark(cases(),POLICIES,client=client,
        inference_sink=lambda value: stored.append(value) or {'verified':True})
    assert len(client.calls)==60 and len(stored)==60
    assert {v['arm'] for v in stored}=={'automation','personal-need'}
    assert output['schema']=='st-rank-semantic-benchmark/v1'
    assert output['total_model_calls']==60
    assert output['rank_model_calls']==0 and output['changes_applied'] is False
    assert output['metrics']['automation']['model_cases']==30
    assert output['metrics']['automation']['brier_mean']==pytest.approx(.3125)
    assert output['metrics']['personal-need']['brier_mean']==pytest.approx(.0625)
    for _, arguments in client.calls:
        assert 'expected' not in arguments['state'] and 'urn:independent-label' not in arguments['state']
        assert 'if' in arguments['instructions'].lower()  # explicit abstain direction


def test_semantic_only_validates_entire_cohort_before_any_spend():
    data=cases();data[-1]['expected']['flags']['automation']=None
    client=NoulsOnly()
    with pytest.raises(rank.TriageError,match='semantic'):
        rank.semantic_benchmark(data,POLICIES,client=client,inference_sink=lambda _:{'verified':True})
    assert client.calls==[]


def test_semantic_only_refused_quarantine_stops_after_one_call():
    client=NoulsOnly()
    with pytest.raises(rank.TriageError,match='quarantine'):
        rank.semantic_benchmark(cases(),POLICIES,client=client,inference_sink=lambda _:{'verified':False})
    assert len(client.calls)==1


def test_semantic_report_cannot_be_admitted_as_rank_benchmark():
    result=rank.semantic_benchmark(cases(),POLICIES)
    assert result['total_model_calls']==0
    assert result['metrics']['automation']['brier_mean'] is None
    with pytest.raises(rank.TriageError):
        rank.admitted_model(result,{},POLICIES,NOW)


def test_cli_semantic_benchmark_is_under_existing_rank_surface():
    args=cli.build_parser().parse_args(['work','triage','--rank-proposals','--benchmark','cases.jsonl',
                                       '--rank-semantic-only','--rank-rules','rules.json'])
    assert args.rank_semantic_only is True


def test_semantic_only_invalid_last_owner_evidence_refuses_before_spend():
    data=cases(); data[-1]['owner_states']={'worker':'maybe'}
    client=NoulsOnly()
    with pytest.raises(rank.TriageError,match='owner evidence'):
        rank.semantic_benchmark(data,POLICIES,client=client,inference_sink=lambda _:{'verified':True})
    assert client.calls==[]


def test_semantic_only_cli_cannot_be_used_for_live_rank_without_benchmark(tmp_path):
    from types import SimpleNamespace as NS
    args=NS(rank_rules=str(tmp_path/'bindings.json'),publish=False,benchmark=None,rank_semantic_only=True)
    (tmp_path/'bindings.json').write_text('[]')
    from unittest.mock import patch
    with patch.object(rank,'rules',return_value=POLICIES):
        with pytest.raises(rank.TriageError,match='frozen benchmark'):
            rank.run(args,None,None,None,host='here',peers=[])


def test_semantic_only_model_change_preserves_both_verdicts_then_stops():
    class Changing(NoulsOnly):
        def call(self, tool, arguments):
            result=super().call(tool, arguments)
            result['model']='model'+str(len(self.calls))
            return result
    client=Changing(); stored=[]
    with pytest.raises(rank.TriageError,match='model changed'):
        rank.semantic_benchmark(cases(),POLICIES,client=client,
            inference_sink=lambda value: stored.append(value) or {'verified':True})
    assert len(client.calls)==2 and len(stored)==2
