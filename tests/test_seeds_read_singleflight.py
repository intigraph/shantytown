"""Concurrent display cache misses must share one actual wire fetch."""
from concurrent.futures import ThreadPoolExecutor
import threading
import time
from urllib.error import HTTPError
import os
import subprocess
import sys

import pytest

from shantytown import seeds_read_cache as cache
from test_seeds_read_cache import read, service  # noqa: F401


def test_simultaneous_stale_misses_share_one_wire_fetch(service):
    proof, state = service
    state['delay'] = .2
    barrier = threading.Barrier(8)

    def caller():
        with cache.stale_ok():
            barrier.wait(timeout=5)
            return read(proof)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: caller(), range(8)))
    assert all(row == results[0] for row in results)
    assert state['queries'] == 1


def test_exact_and_disabled_stale_reads_do_not_enter_singleflight(service, monkeypatch):
    proof, state = service
    monkeypatch.setenv('ST_SEEDS_STALE_TTL', '0')
    state['delay'] = .1
    barrier = threading.Barrier(2)

    def caller():
        with cache.stale_ok():
            barrier.wait(timeout=5)
            return read(proof)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: caller(), range(2)))
    assert state['queries'] == 2


def test_simultaneous_failed_fetches_share_one_refusal(service):
    proof, state = service
    state.update(fail_query=True, delay=.2)
    barrier = threading.Barrier(8)

    def caller():
        with cache.stale_ok():
            barrier.wait(timeout=5)
            try:
                read(proof)
            except (HTTPError, RuntimeError):
                return 'refused'
            return 'unexpected success'

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(lambda _: caller(), range(8))) == ['refused'] * 8
    assert state['queries'] == 1


def test_failed_flight_never_publishes_a_successful_empty_answer(service):
    proof, state = service
    state['fail_query'] = True
    with cache.stale_ok(), pytest.raises(HTTPError):
        read(proof)
    state['fail_query'] = False
    # A subsequent success is admitted after the bounded failure backoff.
    time.sleep(1.05)
    with cache.stale_ok():
        result = read(proof)
    assert result['rows'][0]['value'] == 'before'
    assert state['queries'] == 2


def test_separate_processes_share_the_same_flight(service):
    proof, state = service
    state['delay'] = .3
    script = '''
import sys
from types import SimpleNamespace
from shantytown import seeds_plate, seeds_read_cache
sys.stdin.readline()
with seeds_read_cache.stale_ok():
    result = seeds_plate._query(SimpleNamespace(quipu_url=sys.argv[1]), "SELECT processes", 5)
assert result["rows"][0]["value"] == "before"
'''
    children = [subprocess.Popen([sys.executable, '-c', script, proof.quipu_url],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, env=dict(os.environ))
                for _ in range(4)]
    try:
        for child in children:
            child.stdin.write('\n')
            child.stdin.flush()
        for child in children:
            out, err = child.communicate(timeout=10)
            assert child.returncode == 0, (out, err)
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait()
    assert state['queries'] == 1


def test_busy_flight_times_out_without_duplicate_fetch(tmp_path):
    from shantytown.seeds_read_flight import coalesce, flight
    called = []
    with flight(tmp_path, ['same'], 1):
        with pytest.raises(TimeoutError, match='still in flight'):
            coalesce(tmp_path, ['same'], .02, lookup=lambda: (None, None),
                     fetch=lambda: called.append('duplicate'))
    assert called == []


def test_flight_rejects_an_untrusted_lock_instead_of_following_it(tmp_path):
    from shantytown.seeds_read_flight import flight
    with flight(tmp_path, ['same'], 1):
        pass
    lock = next(tmp_path.glob('flight-*'))
    target = tmp_path / 'outside'
    target.write_text('retained')
    lock.unlink()
    lock.symlink_to(target)
    with pytest.raises(OSError):
        with flight(tmp_path, ['same'], 1):
            pytest.fail('untrusted flight admitted')
    assert target.read_text() == 'retained'


@pytest.mark.parametrize('timeout', [float('nan'), float('inf'), float('-inf')])
def test_invalid_timeout_cannot_create_an_unbounded_flight(tmp_path, timeout):
    from shantytown.seeds_read_flight import flight
    with pytest.raises(ValueError, match='timeout'):
        with flight(tmp_path, ['same'], timeout):
            pytest.fail('invalid timeout admitted')


def test_background_busy_refuses_before_waiting_on_a_held_flight(service, monkeypatch):
    from shantytown import quipu_busy
    from shantytown.seeds_read_flight import flight
    proof, state = service
    monkeypatch.setenv('QUIPU_PRIORITY', 'background')
    quipu_busy.record(proof.quipu_url, 30)
    with flight(cache._directory(), [proof.quipu_url, 'SELECT owner-one'], 1):
        with cache.stale_ok(), pytest.raises(quipu_busy.QuipuBusy):
            read(proof)
    assert state['queries'] == state['watermarks'] == 0


def test_failure_does_not_block_another_key_in_the_same_stripe(tmp_path):
    import hashlib
    import json
    from shantytown.seeds_read_flight import coalesce
    stripe = lambda key: int(hashlib.sha256(json.dumps([key]).encode()).hexdigest()[:2], 16) % 64
    first = 'first'
    other = next(str(n) for n in range(1000) if stripe(str(n)) == stripe(first))
    def fail():
        raise RuntimeError('private failure details')
    with pytest.raises(RuntimeError, match='private failure'):
        coalesce(tmp_path, [first], 1, lookup=lambda: (None, None), fetch=fail)
    assert coalesce(tmp_path, [other], 1, lookup=lambda: (None, None), fetch=lambda: 'ok') == 'ok'
    from shantytown.seeds_read_flight import SharedReadFailed
    with pytest.raises(SharedReadFailed):
        coalesce(tmp_path, [first], 1, lookup=lambda: (None, None), fetch=fail)
    assert 'private failure' not in next(tmp_path.glob('flight-*')).read_text()


def test_failed_flight_is_shared_between_processes(service):
    proof, state = service
    state.update(fail_query=True, delay=.3)
    script = """
import sys
from types import SimpleNamespace
from shantytown import seeds_plate, seeds_read_cache
from urllib.error import HTTPError
sys.stdin.readline()
try:
    with seeds_read_cache.stale_ok():
        seeds_plate._query(SimpleNamespace(quipu_url=sys.argv[1]), "SELECT failed-processes", 5)
except (HTTPError, RuntimeError):
    sys.exit(0)
sys.exit(1)
"""
    children = [subprocess.Popen([sys.executable, '-c', script, proof.quipu_url],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, env=dict(os.environ))
                for _ in range(4)]
    try:
        for child in children:
            child.stdin.write('\n')
            child.stdin.flush()
        for child in children:
            out, err = child.communicate(timeout=10)
            assert child.returncode == 0, (out, err)
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait()
    assert state['queries'] == 1
