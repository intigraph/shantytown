"""Priority/rank ordering agrees across tracker plate and fleet feed."""
import pytest
from shantytown.protocols import plate_key, rank_order
from shantytown.sd import SdTracker
from test_plate_readiness import FakeStore, row
from shantytown.beads import plate


def test_rank_drives_actual_plate_without_moving_priority_or_lifecycle():
    items = [row('old', priority=1), row('ranked', priority=1), row('urgent', priority=0)]
    items[1]['rank'] = '2'
    assert plate(FakeStore(items[:2], ready_ids=['old', 'ranked']), 'ada').id == 'ranked'
    assert plate(FakeStore(items, ready_ids=[x['id'] for x in items]), 'ada').id == 'urgent'
    assert plate_key('in_progress', 4, 'held', rank='9') < plate_key('open', 0, 'new', rank='-9')


def test_feed_exact_decimals_and_unranked_oldest():
    rows = [{'id': ident, 'priority': priority, 'rank': rank, 'created_at': created}
            for ident, priority, rank, created in [
                ('old', 1, None, '2026-01-01T00:00:00Z'),
                ('new', 1, None, '2026-01-02T00:00:00Z'),
                ('high', 0, None, '2026-01-03T00:00:00Z'),
                ('fraction', 1, '900000000000000000.000000001', '2026-01-03T00:00:00Z'),
                ('integer', 1, '900000000000000000', '2026-01-04T00:00:00Z')]]
    assert [r['id'] for r in SdTracker._tend_order(rows)] == ['high', 'integer', 'fraction', 'old', 'new']


@pytest.mark.parametrize('rank', ['NaN', '1e3', 3, '1.0000000001', '9000000000000000001'])
def test_malformed_rank_is_unknown_not_unranked(rank):
    with pytest.raises(ValueError):
        rank_order(rank)


def test_anchor_top_list_uses_rank_but_coming_due_keeps_deadlines():
    from types import SimpleNamespace
    from datetime import datetime, timezone
    from shantytown.answer import Answer
    from shantytown.due_brief import projected
    rows = [dict(id='older',title='Old',status='open',priority=1,created_at='2026-01-01T00:00:00Z',due_at='2026-10-17T00:00:00Z'),
            dict(id='ranked',title='Ranked',status='open',priority=1,rank='1',created_at='2026-01-02T00:00:00Z',due_at='2026-10-18T00:00:00Z')]
    tracker=SimpleNamespace(decision_rows=lambda _: Answer.complete_read(rows,how='private fixture'))
    answer=projected(tracker,'worker',now=datetime(2026,10,17,tzinfo=timezone.utc)).exact()
    assert [r['id'] for r in answer['top']]==['ranked','older']
    assert [r['id'] for r in answer['coming']]==['older','ranked']


@pytest.mark.parametrize('older,newer', [
    ('2026-01-01T01:00:00+02:00', '2026-01-01T00:00:00Z'),
    ('2026-01-01T00:00:00Z', '2026-01-01T00:00:00.1Z'),
    ('2026-01-01T00:00:00.000000001Z', '2026-01-01T00:00:00.000000002Z'),
    ('2026-01-01T00:00:00.999999999Z', '2026-01-01T00:00:01Z'),
])
def test_chronological_keys_across_fleet_plate_and_advisory(older, newer):
    import copy
    from types import SimpleNamespace
    from datetime import datetime, timezone
    from shantytown.answer import Answer
    from shantytown.due_brief import projected
    # IDs deliberately oppose chronological order, exposing truncated ties.
    rows = [dict(id=ident, title=ident, status='open', priority=1,
                 created_at=stamp, due_at=stamp)
            for ident, stamp in [('zolder', older), ('anewer', newer)]]
    original = copy.deepcopy(rows)
    assert [r['id'] for r in SdTracker._tend_order(rows)] == ['zolder', 'anewer']
    keys = [plate_key('open', 1, r['id'], created_at=r['created_at']) for r in rows]
    assert keys[0] < keys[1]
    for r in rows:
        r['rank'] = '1'
    tracker = SimpleNamespace(decision_rows=lambda _: Answer.complete_read(rows, how='fixture'))
    packet = projected(tracker, 'fixture', now=datetime(2026, 1, 1, tzinfo=timezone.utc)).exact()
    assert [r['id'] for r in packet['top']] == ['zolder', 'anewer']
    assert [r['id'] for r in packet['coming']] == ['zolder', 'anewer']
    assert [r['due_at'] for r in packet['top']] == [older, newer]
    for r in rows:
        del r['rank']
    assert rows == original


@pytest.mark.parametrize('left,right', [
    ('2026-01-01T01:00:00+02:00', '2025-12-31T23:00:00Z'),
    ('2026-01-01T00:00:00.1Z', '2026-01-01T00:00:00.100000000+00:00'),
    ('2026-01-01T00:00:00-01:00', '2026-01-01T01:00:00Z'),
])
def test_equivalent_instants_keep_deterministic_id_tie(left, right):
    from shantytown.protocols import time_order
    assert time_order(left) == time_order(right)
    rows = [dict(id=i, priority=1, created_at=t, rank='1', due_at=t)
            for i, t in [('z', left), ('a', right)]]
    assert [r['id'] for r in SdTracker._tend_order(rows)] == ['a', 'z']


@pytest.mark.parametrize('bad', ['', '2026-01-01', '2026-01-01T00:00:00',
                                 'not-time', '2026-02-30T00:00:00Z',
                                 '2026-01-01T00:00:00.0000000001Z',
                                 '2026-01-01T00:00:00+14:01'])
def test_supplied_unknown_time_does_not_become_oldest(bad):
    from shantytown.protocols import time_order
    with pytest.raises(ValueError):
        time_order(bad)
    with pytest.raises(ValueError):
        rank_order('1', due_at=bad)


def test_coming_due_cutoff_keeps_nanosecond_precision():
    from types import SimpleNamespace
    from datetime import datetime, timezone
    from shantytown.answer import Answer
    from shantytown.due_brief import projected
    rows = [dict(id=ident, title=ident, status='open', priority=1, rank='1',
                 created_at='2026-01-01T00:00:00Z', due_at=stamp)
            for ident, stamp in [('cutoff', '2026-01-04T00:00:00Z'),
                                 ('later', '2026-01-04T00:00:00.000000001Z')]]
    tracker = SimpleNamespace(decision_rows=lambda _: Answer.complete_read(rows, how='fixture'))
    packet = projected(tracker, 'fixture', now=datetime(2026, 1, 1, tzinfo=timezone.utc)).exact()
    assert [r['id'] for r in packet['coming']] == ['cutoff']
