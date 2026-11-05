"""aegis-59jx: one missing or unreadable item never aborts the cost report."""
import io
import json
import subprocess
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

import pytest

from shantytown import cost


def _show(table):
    def show(_config, bead):
        value = table[bead]
        if isinstance(value, BaseException):
            raise value
        return value
    return show


def test_missing_and_unreadable_items_are_listed_not_raised(monkeypatch):
    monkeypatch.setattr(cost, 'show', _show({
        'p-ok': {'id': 'p-ok', 'status': 'open'},
        'p-gone': RuntimeError('sd: no seed with id p-gone'),
        'p-slow': subprocess.TimeoutExpired(['sd', 'show', 'p-slow'], 30),
        'p-odd': ValueError('tracker read did not return the requested item'),
    }))
    records, unresolved = cost.read_records({}, ['p-gone', 'p-odd', 'p-ok', 'p-slow'])
    assert records == {'p-ok': {'id': 'p-ok', 'status': 'open'}}
    assert [(u['bead'], u['reason']) for u in unresolved] == [
        ('p-gone', 'missing'), ('p-odd', 'unreadable'), ('p-slow', 'unreadable')]
    assert 'no seed with id p-gone' in unresolved[0]['detail']


def test_unexpected_exception_types_still_propagate(monkeypatch):
    # Only tracker-read failures are absorbed; a programming error is not.
    monkeypatch.setattr(cost, 'show', _show({'p-bug': TypeError('bug')}))
    with pytest.raises(TypeError):
        cost.read_records({}, ['p-bug'])


def _result(unresolved):
    return {'scope': 'supplied sources, not lifetime', 'groups': [], 'errors': [],
            'receipt': 'r', 'unresolved_items': unresolved}


@pytest.mark.parametrize('reason', ['missing', 'unreadable'])
def test_report_mode_returns_report_naming_the_item(monkeypatch, reason):
    item = {'bead': 'p-x', 'reason': reason, 'detail': 'why'}
    monkeypatch.setattr(cost, 'retrieve', lambda *_: (_result([item]), {}, {}))
    out = io.StringIO()
    with redirect_stdout(out):
        assert cost._run_selected(SimpleNamespace(root=Path('/synthetic'), sync=False, bead=None,
                                                  json=True), {}, Path('/synthetic/state')) == 0
    assert json.loads(out.getvalue())['unresolved_items'] == [item]


def test_bead_text_mode_prints_the_unresolved_item(monkeypatch):
    item = {'bead': 'p-x', 'reason': 'missing', 'detail': 'sd: no seed with id p-x'}
    monkeypatch.setattr(cost, 'retrieve', lambda *_: (_result([item]), {}, {}))
    out = io.StringIO()
    with redirect_stdout(out):
        assert cost._run_selected(SimpleNamespace(root=Path('/synthetic'), sync=False, bead='p-x',
                                                  json=False), {}, Path('/synthetic/state')) == 0
    assert 'cost: item p-x missing: sd: no seed with id p-x' in out.getvalue()


def test_sync_still_refuses_an_unreadable_item_and_names_it(monkeypatch):
    item = {'bead': 'p-slow', 'reason': 'unreadable', 'detail': 'timed out'}
    monkeypatch.setattr(cost, 'retrieve', lambda *_: (_result([item]), {}, {}))
    monkeypatch.setattr(cost, '_publish_metrics', lambda *_a, **_k: pytest.fail('published on unknown read'))
    with pytest.raises(RuntimeError, match='tracker read UNKNOWN for p-slow'):
        cost._run_selected(SimpleNamespace(root=Path('/synthetic'), sync=True, bead=None, json=False),
                           {}, Path('/synthetic/state'))


def test_sync_proceeds_past_a_missing_item(monkeypatch):
    item = {'bead': 'p-gone', 'reason': 'missing', 'detail': 'sd: no seed with id p-gone'}
    published = []
    monkeypatch.setattr(cost, 'retrieve', lambda *_: (_result([item]), {}, {}))
    monkeypatch.setattr(cost, '_publish_metrics', lambda _c, result=None, **_k: published.append(result))
    monkeypatch.setattr(cost, 'comment_closed', lambda *_a: [])
    out = io.StringIO()
    with redirect_stdout(out):
        assert cost._run_selected(SimpleNamespace(root=Path('/synthetic'), sync=True, bead=None,
                                                  json=False), {}, Path('/synthetic/state')) == 0
    assert published and published[0]['unresolved_items'] == [item]


def test_only_items_bound_to_measured_sessions_are_read(tmp_path, monkeypatch):
    """A binding for a session absent from the sources can never match a request,
    so its item is not read from the tracker (2149 reads -> 11 on 2026-11-02)."""
    import sqlite3
    from shantytown import task_order
    conn = sqlite3.connect(tmp_path / 'stats.sqlite')
    conn.executescript(task_order._SCHEMA)
    rows = [(10, 'worker', 'live', 'p-live'), (5, 'worker', 'gone', 'p-old'),
            (6, 'other', 'gone2', 'p-other')]
    for stamp, agent, session, task in rows:
        conn.execute('INSERT INTO task_contexts(ts,agent,session,task,paired_start) VALUES (?,?,?,?,1)',
                     (stamp, agent, session, task))
    conn.commit(); conn.close()
    calls = tmp_path / 'calls.jsonl'
    script = tmp_path / 'fake_retrieve.py'
    script.write_text(
        'import json, sys\n'
        f'open({str(calls)!r}, "a").write(open(sys.argv[1]).read() + "\\n")\n'
        'print(json.dumps({"status": "retrieved", "result": {"groups": [], "errors": [],\n'
        '    "records": [{"agent": "worker", "session": "live"}]}}))\n')
    read = []
    monkeypatch.setattr(cost, 'show', lambda _c, bead: read.append(bead) or {'id': bead, 'status': 'open'})
    config = {'rig': 'project', 'retrieve_script': str(script),
              'sources': [{'agent': 'worker', 'harness': 'claude', 'path': '/x'},
                          {'agent': 'other', 'harness': 'claude', 'path': '/y'}]}
    result, records, method = cost.retrieve(tmp_path, config)
    assert read == ['p-live'] and list(records) == ['p-live']
    assert [b['bead'] for b in method['params']['bindings']] == ['p-live']
    passes = [json.loads(line) for line in calls.read_text().splitlines()]
    assert [len(p['params']['bindings']) for p in passes] == [0, 1]
