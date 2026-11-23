"""SDK runner coalescing; these controls do not measure HTTP amplification."""
from concurrent.futures import ThreadPoolExecutor
import json
import subprocess
import threading
import time

import pytest
from shantytown import sd, seeds_read_cache, actor_identity

# Same adapter-test admission as test_sd_backend: the runner is replaced by
# the fixture below, so no executable or store is reached.
pytestmark = pytest.mark.real_store


@pytest.fixture
def sdk(tmp_path, monkeypatch):
    monkeypatch.setenv('SHANTY_AGENT', 'fixture')
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path / 'cache'))
    monkeypatch.setenv('ST_SEEDS_STALE_TTL', '60')
    monkeypatch.setenv('ST_SEEDS_READ_CACHE', '1')
    monkeypatch.setattr(actor_identity, 'authenticated_actor', lambda: None)
    monkeypatch.setattr(actor_identity, 'config_environment', lambda: {})
    tracker = sd.SdTracker(repo=str(tmp_path), prefix='fixture')
    monkeypatch.setattr(tracker, 'prove_store', lambda: None)
    monkeypatch.setattr(type(tracker), '_bin', property(lambda _: 'fixture-sdk'))
    monkeypatch.setattr(tracker, '_location', lambda: [])
    state = dict(calls=0, mode='ok', value='populated', invalidate=False)
    lock = threading.Lock()

    def runner(cmd, **_options):
        with lock:
            state['calls'] += 1
            value = state['value']
        time.sleep(.1)
        if state['mode'] == 'timeout':
            raise subprocess.TimeoutExpired(cmd, 1)
        if state['mode'] == 'failure':
            return subprocess.CompletedProcess(cmd, 3, 'partial', 'fixture-error')
        if state['invalidate']:
            state['invalidate'] = False
            seeds_read_cache.invalidate_stale()
            state['value'] = 'after-write'
        owner = cmd[cmd.index('--assignee') + 1]
        return subprocess.CompletedProcess(cmd, 0, json.dumps({'rows': [value], 'owner': owner}), 'fixture-note')

    monkeypatch.setattr(sd.subprocess, 'run', runner)
    return tracker, state


def call(tracker, owner='fixture'):
    return tracker._bd('list', '--assignee', owner, '--json')


def test_simultaneous_sdk_stale_misses_dispatch_one_runner(sdk):
    tracker, state = sdk
    barrier = threading.Barrier(8)

    def read(_):
        with seeds_read_cache.stale_ok():
            barrier.wait(timeout=5)
            return call(tracker).stdout

    with ThreadPoolExecutor(max_workers=8) as pool:
        values = list(pool.map(read, range(8)))
    assert all(json.loads(v)['rows'] == ['populated'] for v in values)
    assert state['calls'] == 1
    with seeds_read_cache.stale_ok():
        assert json.loads(call(tracker).stdout)['rows'] == ['populated']
    assert state['calls'] == 1


def test_failed_sdk_result_preserves_evidence_and_is_not_cached(sdk):
    tracker, state = sdk
    state['mode'] = 'failure'
    with seeds_read_cache.stale_ok():
        failed = call(tracker)
        assert (failed.returncode, failed.stdout, failed.stderr) == (3, 'partial', 'fixture-error')
        state['mode'] = 'ok'
        fresh = call(tracker)
        assert fresh.returncode == 0 and fresh.stderr == 'fixture-note'
        assert call(tracker).stderr == ''  # Existing cached-output contract.
    assert state['calls'] == 2


def test_sdk_timeout_releases_flight_without_publishing(sdk):
    tracker, state = sdk
    state['mode'] = 'timeout'
    with seeds_read_cache.stale_ok():
        with pytest.raises(subprocess.TimeoutExpired):
            call(tracker)
        state['mode'] = 'ok'
        assert call(tracker).returncode == 0
    assert state['calls'] == 2


def test_own_write_during_sdk_fetch_prevents_publication(sdk):
    tracker, state = sdk
    state['invalidate'] = True
    with seeds_read_cache.stale_ok():
        assert json.loads(call(tracker).stdout)['rows'] == ['populated']
        assert json.loads(call(tracker).stdout)['rows'] == ['after-write']
    assert state['calls'] == 2


def test_rollback_keeps_sdk_reads_live(sdk, monkeypatch):
    tracker, state = sdk
    monkeypatch.setenv('ST_SEEDS_STALE_TTL', '0')
    with seeds_read_cache.stale_ok():
        call(tracker)
        call(tracker)
    assert state['calls'] == 2


def test_other_owner_retains_its_own_sdk_cache_key(sdk):
    tracker, state = sdk
    with seeds_read_cache.stale_ok():
        for owner in ('fixture-a', 'fixture-b', 'fixture-a'):
            assert json.loads(call(tracker, owner).stdout)['owner'] == owner
    assert state['calls'] == 2
