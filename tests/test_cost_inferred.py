"""aegis-59jx step 2a: inferred-held attribution from st stop events, kept separate."""
import json
import sqlite3
from pathlib import Path

from shantytown import cost, cost_daily, task_order


def stops(root, rows):
    events = Path(root) / 'events'
    events.mkdir(exist_ok=True)
    for i, (agent, ts, item, status) in enumerate(rows):
        (events / f'ev-{i}.json').write_text(json.dumps(
            {'kind': 'stop', 'frm': agent, 'ts': ts, 'item': item, 'item_status': status}))


def test_runs_follow_the_same_in_progress_item_and_break_on_change(tmp_path):
    stops(tmp_path, [('w', 10, 'p', 'in_progress'), ('w', 20, 'p', 'in_progress'),
                     ('w', 30, 'p', 'in_progress'), ('w', 40, 'q', 'in_progress'),
                     ('w', 50, 'q', 'in_progress'), ('w', 60, 'q', 'closed'),
                     ('w', 70, None, None), ('other', 15, 'x', 'in_progress'),
                     ('other', 25, 'x', 'in_progress')])
    (tmp_path / 'events' / 'not-a-stop.json').write_text(json.dumps({'kind': 'nudge', 'frm': 'w', 'ts': 35}))
    held = cost.held_bindings(tmp_path, 'rig', {('w', 's1'), ('w', 's2')}, 0)
    spans = sorted((b['bead'], b['session'], b['start'], b['end']) for b in held)
    # p runs 10->30; p->q at 30/40 is a change, not a run; q 40->50; closed at 60 ends it.
    assert spans == [('p', 's1', 10, 30), ('p', 's2', 10, 30), ('q', 's1', 40, 50), ('q', 's2', 40, 50)]
    assert {b['basis'] for b in held} == {'inferred-held'}
    # 'other' has no measured session in the sources, so it gets no binding.
    assert all(b['agent'] == 'w' for b in held)


def _fake(tmp_path, bases):
    calls = tmp_path / 'calls.jsonl'
    script = tmp_path / 'fake_retrieve.py'
    script.write_text(
        'import json, sys\n'
        f'open({str(calls)!r}, "a").write(open(sys.argv[1]).read() + "\\n")\n'
        f'print(json.dumps({{"status": "retrieved", "result": {{"groups": [], "errors": [],\n'
        f'    "binding_bases": {json.dumps(bases)},\n'
        '    "records": [{"agent": "w", "session": "s1"}]}}))\n')
    conn = sqlite3.connect(tmp_path / 'stats.sqlite')
    conn.executescript(task_order._SCHEMA)
    conn.commit(); conn.close()
    stops(tmp_path, [('w', 9e9 - 20, 'p', 'in_progress'), ('w', 9e9 - 10, 'p', 'in_progress')])
    return calls, {'rig': 'rig', 'retrieve_script': str(script), 'since_hours': 10 ** 6,
                   'sources': [{'agent': 'w', 'harness': 'claude', 'path': '/x'}]}


def test_inferred_bindings_are_sent_only_to_a_camayoc_that_ranks_them(tmp_path, monkeypatch):
    monkeypatch.setattr(cost, 'show', lambda *_: {'id': 'x', 'status': 'open'})
    calls, config = _fake(tmp_path, ['declared', 'inferred-held'])
    result, _, method = cost.retrieve(tmp_path, config)
    assert [b['basis'] for b in method['params']['bindings']] == ['inferred-held']
    assert result['inference']['status'] == 'used'


def test_older_camayoc_gets_no_inferred_bindings(tmp_path, monkeypatch):
    monkeypatch.setattr(cost, 'show', lambda *_: {'id': 'x', 'status': 'open'})
    calls, config = _fake(tmp_path, [])
    result, _, method = cost.retrieve(tmp_path, config)
    assert method['params']['bindings'] == []
    assert result['inference']['status'].startswith('unavailable')


def _groups():
    counts = {'input_uncached': 1, 'cache_read_input': 2, 'cache_write_input': 3, 'output': 4}
    base = {'rig': 'r', 'bead': 'p', 'agent': 'w', 'harness': 'claude', 'model': 'm',
            'counts': counts, 'tokens': 10, 'requests': 1, 'sessions': ['s'], 'coverage': 'observed'}
    return {'scope': 'x', 'groups': [base, {**base, 'basis': 'inferred-held', 'coverage': 'inferred',
                                            'counts': {k: v * 100 for k, v in counts.items()}}]}


def test_receipt_carries_declared_spend_only():
    digest, body = cost.receipt(_groups(), 'p')
    only_declared = {'scope': 'x', 'groups': [_groups()['groups'][0]]}
    assert (digest, body) == cost.receipt(only_declared, 'p')
    assert '100/' not in body


def test_inferred_spend_has_its_own_metric_series():
    text = cost.metrics(_groups())
    observed = [l for l in text.splitlines() if l.startswith('st_bead_tokens_total{')]
    inferred = [l for l in text.splitlines() if l.startswith('st_bead_tokens_inferred_total{')]
    assert len(observed) == 4 and len(inferred) == 4
    assert all(not l.endswith(('100', '200', '300', '400')) for l in observed)
    assert sum(l.startswith('st_bead_cost_coverage{') for l in text.splitlines()) == 1


def test_daily_keeps_inferred_rows_apart():
    rec = {'harness': 'claude', 'session': 's', 'agent': 'w', 'rig': 'r', 'bead': 'p', 'model': 'm',
           'at': 1000.0, 'counts': {k: 1 for k in cost_daily.KINDS}}
    result = {'schema_version': 1, 'errors': [], 'receipt': 'x', 'records': [
        {**rec, 'id': 'a', 'attribution': 'attributed'},
        {**rec, 'id': 'b', 'attribution': 'inferred held item'}]}
    (projected,) = cost_daily.project(result, now=2000.0)
    rows = projected['rows']
    assert len(rows) == 2
    assert sorted(r.get('basis', 'declared') for r in rows) == ['declared', 'inferred-held']
    assert next(r for r in rows if 'basis' not in r)['attribution_known'] is True
