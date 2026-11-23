"""Distinct direct reads must share the configured host budget across processes."""
import os
import json
import pytest

from shantytown import quipu_read_budget as budget
import subprocess
import sys

from test_seeds_read_cache import service  # noqa: F401


def test_distinct_native_reads_share_a_host_budget(service, monkeypatch):
    proof, state = service
    monkeypatch.setenv('ST_QUIPU_READS_PER_MINUTE', '2')
    script = '''
import sys
from types import SimpleNamespace
from shantytown import seeds_plate, seeds_read_cache
sys.stdin.readline()
try:
    with seeds_read_cache.direct_reads():
        result = seeds_plate._query(SimpleNamespace(quipu_url=sys.argv[1]),
                                    "SELECT distinct-budget-" + sys.argv[2], 5)
    assert result["rows"][0]["value"] == "before"
except ValueError:
    sys.exit(75)
sys.exit(0)
'''
    children = [subprocess.Popen([sys.executable, '-c', script, proof.quipu_url, str(i)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, env=dict(os.environ)) for i in range(3)]
    try:
        for child in children:
            child.stdin.write('\n')
            child.stdin.flush()
        results = []
        for child in children:
            out, err = child.communicate(timeout=10)
            assert child.returncode in (0, 75), (out, err)
            results.append(child.returncode)
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait()
    assert state['queries'] == 2
    assert sorted(results) == [0, 0, 75]


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path / 'cache'))
    monkeypatch.setenv('ST_QUIPU_READS_PER_MINUTE', '2')
    return tmp_path / 'cache' / 'shantytown' / 'read-budget-v1'


def test_sliding_window_expiry_origin_scope_and_limit_changes(ledger, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(budget.time, 'time', lambda: clock[0])
    budget.admit('http://EXAMPLE.test/query')
    clock[0] += 10
    budget.admit('http://example.test:80/watermark')
    with pytest.raises(budget.ReadBudgetRefused, match='exhausted'):
        budget.admit('http://example.test/changes')
    budget.admit('http://other.test/query')
    clock[0] = 1060
    budget.admit('http://example.test/query')
    with pytest.raises(budget.ReadBudgetRefused):
        budget.admit('http://example.test/query')
    monkeypatch.setenv('ST_QUIPU_READS_PER_MINUTE', '1')
    # Lowering the configured limit cannot reset the accumulated charge.
    with pytest.raises(budget.ReadBudgetRefused):
        budget.admit('http://example.test/query')


@pytest.mark.parametrize('value', ['NaN', '-1', '10001', '1.5', ''])
def test_invalid_limit_refuses_instead_of_disabling(ledger, monkeypatch, value):
    monkeypatch.setenv('ST_QUIPU_READS_PER_MINUTE', value)
    with pytest.raises(budget.ReadBudgetRefused, match='invalid'):
        budget.admit('http://example.test')


def test_corruption_and_clock_regression_refuse_without_reset(ledger, monkeypatch):
    monkeypatch.setattr(budget.time, 'time', lambda: 1000)
    budget.admit('http://example.test')
    entry = next(ledger.glob('*.json'))
    monkeypatch.setattr(budget.time, 'time', lambda: 999)
    with pytest.raises(budget.ReadBudgetRefused, match='unavailable'):
        budget.admit('http://example.test')
    assert json.loads(entry.read_text()) == [1000]
    entry.write_text('malformed')
    with pytest.raises(budget.ReadBudgetRefused, match='unavailable'):
        budget.admit('http://example.test')
    assert entry.read_text() == 'malformed'


def test_symlink_and_public_ledger_refuse_without_touching_target(ledger, tmp_path):
    budget.admit('http://example.test')
    entry = next(ledger.glob('*.json'))
    entry.chmod(0o644)
    with pytest.raises(budget.ReadBudgetRefused):
        budget.admit('http://example.test')
    entry.unlink()
    target = tmp_path / 'outside'
    target.write_text('retained')
    entry.symlink_to(target)
    with pytest.raises(budget.ReadBudgetRefused):
        budget.admit('http://example.test')
    assert target.read_text() == 'retained'


def test_native_registry_events_and_deadline_share_the_same_charge(service, monkeypatch):
    from shantytown import seeds_plate, seeds_read_cache, quipu, quipu_events, _deadline_http
    from shantytown.protocols import EventsUnavailable
    proof, state = service
    monkeypatch.setenv('ST_QUIPU_READS_PER_MINUTE', '1')
    with seeds_read_cache.direct_reads():
        assert seeds_plate._query(proof, 'SELECT budget-positive', 5)['rows']
    registry = quipu.QuipuRegistry(proof.quipu_url, onto='https://example.test/')
    with pytest.raises(quipu.QuipuQueryRejected, match='local read refused'):
        registry._query('SELECT registry')
    events = quipu_events.QuipuEvents(proof.quipu_url, onto='https://example.test/')
    with pytest.raises(EventsUnavailable, match='local read refused'):
        events._get('/transactions?since=0')
    with pytest.raises(budget.ReadBudgetRefused):
        seeds_read_cache._watermark_once(proof.quipu_url, 5, lambda *a, **kw: pytest.fail('dispatched'))
    monkeypatch.setattr(_deadline_http.subprocess, 'Popen', lambda *a, **kw: pytest.fail('child dispatched'))
    with pytest.raises(budget.ReadBudgetRefused):
        _deadline_http.post(proof.quipu_url + '/query', '{}', {}, timeout=2, max_bytes=10)
    assert state['queries'] == 1 and state['watermarks'] == 0


def test_failed_attempt_keeps_its_charge(service, monkeypatch):
    from shantytown import seeds_plate, seeds_read_cache
    from urllib.error import HTTPError
    proof, state = service
    monkeypatch.setenv('ST_QUIPU_READS_PER_MINUTE', '1')
    state['fail_query'] = True
    with seeds_read_cache.direct_reads():
        with pytest.raises(HTTPError):
            seeds_plate._query(proof, 'SELECT failed', 5)
        with pytest.raises(budget.ReadBudgetRefused):
            seeds_plate._query(proof, 'SELECT failed-again', 5)
    assert state['queries'] == 1


def test_stale_cache_hit_does_not_spend_another_charge(service, monkeypatch):
    from test_seeds_read_cache import read
    from shantytown import seeds_read_cache
    proof, state = service
    monkeypatch.setenv('ST_QUIPU_READS_PER_MINUTE', '2')
    with seeds_read_cache.stale_ok():
        first = read(proof)
        assert first['rows'][0]['value'] == 'before'
        assert read(proof) == first
    assert state['queries'] == 1 and state['watermarks'] == 1


def test_disabled_budget_ignores_ledger_and_keeps_live_reads(service, monkeypatch):
    from shantytown import seeds_plate, seeds_read_cache
    proof, state = service
    monkeypatch.setenv('ST_QUIPU_READS_PER_MINUTE', '0')
    with seeds_read_cache.direct_reads():
        for n in range(3):
            assert seeds_plate._query(proof, 'SELECT off-' + str(n), 5)['rows']
    assert state['queries'] == 3


def test_quota_refusal_cannot_fall_back_to_an_unfenced_fetch(ledger, monkeypatch):
    from shantytown import seeds_read_cache
    fetched = []
    def refused(*args):
        raise budget.ReadBudgetRefused('fixture quota refusal')
    monkeypatch.setattr(seeds_read_cache, '_watermark', refused)
    with pytest.raises(budget.ReadBudgetRefused):
        seeds_read_cache.read('http://example.test', 'SELECT fence', 1,
            opener=None, fetch=lambda: fetched.append(True), validate=lambda v: v)
    assert fetched == []
