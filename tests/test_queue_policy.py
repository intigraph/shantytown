from dataclasses import replace
import json

import pytest

from shantytown.protocols import WorkItem
from shantytown.queue_policy import enabled, intake, promotion, refusal, reply


def row(ident='x-1', **fields):
    return dict(id=ident, title='work', status='open', assignee='ellie',
                priority=2, rank='1', lane='next') | fields


def item(**fields):
    return WorkItem(**row(lane='now') | fields)


def test_mode_never_promotes_unknown_to_off():
    assert not enabled(None)
    assert enabled('enforce')
    with pytest.raises(ValueError, match='UNKNOWN'):
        enabled('enfroce')


def test_intake_appends_exact_decimal_and_names_now_without_estimated_date():
    plan = intake([row(rank='1.000000001'), row('x-2', lane='now', rank='0')])
    assert plan['rank'] == '2.000000001' and plan['position'] == 2
    assert plan['would_pause'] == ['x-2']
    assert 'UNKNOWN' in reply('x-3', plan)


@pytest.mark.parametrize('rows', [
    [row(rank=None)], [row(rank=True)], [row(lane='unknown')],
    [row(), row()], [row(str(n)) for n in range(41)],
    [row(str(n), lane='now') for n in range(6)],
])
def test_intake_refuses_partial_ambiguous_and_full_queues(rows):
    with pytest.raises((ValueError, TypeError)):
        intake(rows)


def test_dispatch_refuses_next_even_when_high_priority_and_quote_is_not_a_bypass():
    assert 'not in Now' in refusal(item(lane='next', priority=0), 'ellie', [])


def test_dispatch_rank_not_severity_orders_now_and_preserves_active_custody():
    target = item(priority=0, rank='2')
    assert 'out of order' in refusal(target, 'ellie', [row('x-2', lane='now', rank='1', priority=4)])
    assert 'out of order' in refusal(replace(target, rank='0'), 'ellie',
        [row('x-2', lane='now', rank='9', status='in_progress')])
    assert not refusal(target, 'ellie', [row('x-2', lane='now', rank='3')])


def test_unlaned_predecessor_is_unknown_not_silently_skipped():
    assert 'UNKNOWN' in refusal(item(), 'ellie', [row('x-2', lane=None)])


def test_promotion_retains_verbatim_quote_and_requires_all_bindings():
    quote = 'Please do this NOW.\nKeep the prior work.'
    event = json.loads(promotion(quote, 'operator', True,
                                expected_requester='operator', displaced=['x-2']))
    assert event['quote'] == quote and event['displaced'] == ['x-2']
    for args in [('', 'operator', True), (quote, '', True), (quote, 'operator', False)]:
        with pytest.raises(ValueError):
            promotion(*args)


@pytest.mark.parametrize('quote,requester', [('Please do this now', 'other'),
                                         ('Please queue this', 'operator')])
def test_now_requires_the_configured_operator_now_request(quote, requester):
    with pytest.raises(ValueError, match='configured requester'):
        promotion(quote, requester, True, expected_requester='operator')


def test_requester_policy_cannot_be_assumed_from_the_caller():
    with pytest.raises(ValueError, match='UNKNOWN'):
        promotion('Please do it now', 'operator', True)


def test_selected_item_keeps_its_fresh_directive_evidence():
    rows=[row('a-plain',lane='now'),row('z-operator',lane='now',operator_directive=True)]
    assert refusal(item(id='z-operator'),'ellie',rows)==''
    assert 'z-operator' in refusal(item(id='a-plain'),'ellie',rows)
