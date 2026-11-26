import json

import pytest

from shantytown import cost, cost_plan_share as ps

PLANS = {'acct-a': {'usd': 200, 'period_days': 28, 'window': 'seven_day', 'window_days': 7}}
ACCOUNTS = {'worker': ('acct-a', 0.0)}


def focus(agent='worker', bead='task-a', start=1000.0, end=5000.0, session='s1'):
    return {'rig': 'example', 'bead': bead, 'agent': agent, 'session': session,
            'start': start, 'end': end}


def reading(ts, pct, account='acct-a', resets=99999):
    return {'account': account, 'window': 'seven_day', 'ts': ts, 'pct': pct, 'resets_at': resets}


READINGS = [reading(900, 10.0), reading(5100, 14.0)]


def test_exclusive_interval_converts_window_points_to_plan_dollars():
    [row] = ps.allocate([focus()], READINGS, PLANS, ACCOUNTS)
    # 200 USD over 28 days = 50 USD per 7-day window; 4 points of it = 2 USD.
    assert row['reason'] is None
    assert row['points'] == '4.0'
    assert float(row['usd']) == pytest.approx(2.0)


def reason(**changes):
    args = dict(bindings=[focus()], readings=READINGS, plans=PLANS, accounts=ACCOUNTS)
    args.update(changes)
    [row] = ps.allocate(args.pop('bindings'), **args)[:1]
    assert row['usd'] is None, 'this case must refuse to price'
    return row['reason']


def test_a_concurrent_focus_on_the_account_refuses_to_split_points():
    other = focus(agent='peer', bead='task-b', start=3000.0, end=4000.0, session='s9')
    accounts = {**ACCOUNTS, 'peer': ('acct-a', 0.0)}
    assert 'shared' in reason(bindings=[focus(), other], accounts=accounts)


def test_a_neighbour_inside_the_reading_gap_is_not_ignored():
    # Ends inside the 900..1000 gap before the focus: it overlaps the MEASURED
    # interval though not the focus itself.
    other = focus(agent='peer', bead='task-b', start=500.0, end=950.0, session='s9')
    accounts = {**ACCOUNTS, 'peer': ('acct-a', 0.0)}
    rows = ps.allocate([focus()], READINGS, PLANS, accounts, everyone=[focus(), other])
    assert rows[0]['usd'] is None and 'shared' in rows[0]['reason']


def test_a_concurrent_focus_outside_the_sample_still_counts():
    other = focus(agent='peer', bead='task-b', session='s9')
    rows = ps.allocate([focus()], READINGS, PLANS, {**ACCOUNTS, 'peer': ('acct-a', 0.0)},
                       everyone=[focus(), other])
    assert rows[0]['usd'] is None


def test_an_undeclared_live_agent_on_the_account_blocks_attribution():
    accounts = {**ACCOUNTS, 'idle': ('acct-a', 100.0)}
    assert 'occupancy' in reason(accounts=accounts)


def test_an_agent_relaunched_during_the_interval_makes_occupancy_unknown():
    accounts = {**ACCOUNTS, 'elsewhere': ('acct-b', 2000.0)}
    assert 'occupancy' in reason(accounts=accounts)


def test_an_agent_on_another_account_since_before_is_harmless():
    accounts = {**ACCOUNTS, 'elsewhere': ('acct-b', 0.0)}
    [row] = ps.allocate([focus()], READINGS, PLANS, accounts)
    assert row['usd'] is not None


@pytest.mark.parametrize('readings, expected', [
    ([reading(900, 10.0)], 'brackets'),
    ([reading(0, 10.0), reading(5100, 14.0)], 'exceed'),
    ([reading(900, 10.0), reading(5100, 14.0, resets=1)], 'reset'),
    ([reading(900, 10.0, resets=None), reading(5100, 14.0, resets=None)], 'reset'),
    ([reading(900, 14.0), reading(5100, 10.0)], 'decreased'),
    ([reading(900, 10.0, account='acct-b'), reading(5100, 14.0, account='acct-b')], 'brackets'),
])
def test_unmeasured_windows_are_unknown(readings, expected):
    assert expected in reason(readings=readings)


def test_open_focus_unknown_launch_and_missing_price_are_unknown():
    assert 'open' in reason(bindings=[focus(end=None)])
    assert 'launch' in reason(accounts={})
    assert 'postdates' in reason(accounts={'worker': ('acct-a', 2000.0)})
    assert 'plan price' in reason(plans={})


def test_display_and_metrics_carry_only_measured_dollars(tmp_path):
    rows = ps.allocate([focus(), focus(bead='task-b', start=6000.0, end=None)], READINGS, PLANS, ACCOUNTS)
    result = {'groups': [], 'plan_share': rows}
    text = cost.price_description(result, 'task-a')
    assert 'Plan share USD (measured window points x plan price): 2' in text
    assert 'UNKNOWN (focus still open)' in cost.price_description(result, 'task-b')
    assert 'Plan share USD: UNKNOWN (no focus interval' in cost.price_description(result, 'task-z')
    metrics = cost.metrics(result)
    assert 'st_bead_plan_share_usd{' in metrics and 'bead="task-a"' in metrics
    assert 'bead="task-b"' not in metrics, 'an UNKNOWN share must not be emitted as a sample'


def test_disabled_plan_share_keeps_the_camayoc_reason():
    text = cost.price_description({'groups': [], 'costs': {'groups': [{'bead': 'task-a', 'model': 'm',
        'harness': 'claude', 'basis': 'declared', 'usd': '1', 'priced_tokens': 1, 'tokens': 1}],
        'plan_share_reason': 'camayoc says no'}}, 'task-a')
    assert 'Plan share USD: UNKNOWN (camayoc says no)' in text
    assert ps.project('.', {}, [], []) is None


def test_project_reads_readings_and_launch_stamps(tmp_path):
    stamps = tmp_path / 'governor' / 'account-launches'
    stamps.mkdir(parents=True)
    (stamps / 'worker.json').write_text(json.dumps({'account': 'acct-a', 'born': 0}))
    path = tmp_path / 'readings.jsonl'
    path.write_text(''.join(json.dumps(r) + '\n' for r in READINGS))
    config = {'plan_share': {'readings_file': str(path), 'plans': PLANS}}
    [row] = ps.project(tmp_path, config, [focus()], [focus()])
    assert float(row['usd']) == pytest.approx(2.0)
