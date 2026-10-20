import copy
from datetime import datetime

import pytest

from shantytown import cost_daily

NOW = datetime.fromisoformat('2026-10-16T12:00:00+00:00').timestamp()


def record(identity='one', **changes):
    return {'id': identity, 'harness': 'claude', 'session': 's', 'agent': 'worker',
            'at': '2026-10-15T23:30:00-01:00', 'rig': 'project', 'bead': 'seed-a',
            'model': 'model', 'attribution': 'attributed',
            'counts': dict(input_uncached=4, cache_read_input=3, cache_write_input=2, output=1), **changes}


def result(*records):
    return {'schema_version': 1, 'records': list(records), 'errors': [], 'receipt': 'fixture'}


def test_utc_day_breakdown_and_replay_oracle():
    first = record()
    second = record('two', at='2026-10-15T23:59:59Z')
    snapshots = cost_daily.project(result(first, second, copy.deepcopy(first)), now=NOW)
    assert len(snapshots) == 1
    assert [(r['day'], r['requests'], r['counts']) for r in snapshots[0]['rows']] == [
        ('2026-10-15', 1, dict(input_uncached=4, cache_read_input=3, cache_write_input=2, output=1)),
        ('2026-10-16', 1, dict(input_uncached=4, cache_read_input=3, cache_write_input=2, output=1))]


def test_correction_replaces_session_and_preserves_other_sessions(tmp_path):
    path = tmp_path / 'daily.json'
    original = result(record())
    cost_daily.update(path, original, now=NOW)
    cost_daily.update(path, result(record('other', session='other')), now=NOW)
    corrected = record(bead='seed-b', counts=dict(input_uncached=1, cache_read_input=0, cache_write_input=0, output=0))
    a = cost_daily.update(path, result(corrected), now=NOW)
    b = cost_daily.update(path, result(corrected), now=NOW)
    assert a == b
    rows = [r for s in b['sessions'] for r in s['rows']]
    assert {(r['seed'], r['counts']['output']) for r in rows} == {('seed-a', 1), ('seed-b', 0)}
    assert b['day_coverage'].startswith('UNKNOWN')


def test_unknown_is_preserved_without_fabricated_zero():
    r = record(attribution='no proven focus', bead='unattributed', rig='unknown', model=None,
               counts=dict(input_uncached=None, cache_read_input=3, cache_write_input=2, output=1))
    row = cost_daily.project(result(r), now=NOW)[0]['rows'][0]
    assert row['counts']['input_uncached'] is None
    assert row['counts']['output'] == 1
    assert not row['attribution_known']


@pytest.mark.parametrize('bad', [
    result(),
    result(record(), record(counts=dict(input_uncached=0, cache_read_input=0, cache_write_input=0, output=0))),
    result(record(at='2026-10-15T23:30:00')),
    result(record(at='2026-10-17T00:00:00Z')),
    result(record(counts={'output': 1})),
    result(record(counts=dict(input_uncached=True, cache_read_input=0, cache_write_input=0, output=0))),
    {**result(record()), 'errors': ['parser conflict']},
])
def test_refusal_preserves_last_good(tmp_path, bad):
    path = tmp_path / 'daily.json'
    cost_daily.update(path, result(record()), now=NOW)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        cost_daily.update(path, bad, now=NOW)
    assert path.read_bytes() == before


def test_real_cost_producer_wires_optional_projection(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from shantytown import cost
    r = result(record())
    r['receipt'] = 'same-parser-receipt'
    monkeypatch.setattr(cost, 'retrieve', lambda *_: (r, {}, {}))
    monkeypatch.setattr(cost, '_publish_metrics', lambda *_: None)
    monkeypatch.setattr(cost, 'comment_closed', lambda *_: [])
    monkeypatch.setattr(cost.time, 'time', lambda: NOW)
    path = tmp_path / 'daily.json'
    args = SimpleNamespace(root=tmp_path, sync=True, bead=None, json=False)
    assert cost._run_selected(args, {'daily_output': str(path)}, tmp_path / 'graph.json') == 0
    import json
    saved = json.loads(path.read_text())
    assert saved['sessions'][0]['rows'][0]['counts']['output'] == 1
    assert saved['sessions'][0]['receipt'] == 'same-parser-receipt'


def test_session_agent_change_cannot_duplicate_history(tmp_path):
    path = tmp_path / 'daily.json'
    cost_daily.update(path, result(record()), now=NOW)
    before = path.read_bytes()
    with pytest.raises(ValueError, match='agent changed'):
        cost_daily.update(path, result(record(agent='renamed')), now=NOW)
    assert path.read_bytes() == before
    with pytest.raises(ValueError, match='ambiguous agent'):
        cost_daily.project(result(record(), record('two', agent='renamed')), now=NOW)


def test_malformed_cache_is_preserved(tmp_path):
    path = tmp_path / 'daily.json'
    path.write_text('{"schema_version":1,"sessions":[{}]}')
    before = path.read_bytes()
    with pytest.raises(ValueError, match='malformed'):
        cost_daily.update(path, result(record()), now=NOW)
    assert path.read_bytes() == before
