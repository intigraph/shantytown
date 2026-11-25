"""Only complete, explicitly stale display projections share a host observation."""
from concurrent.futures import ThreadPoolExecutor
import json
import subprocess
import threading
import time

import pytest
from shantytown import seeds_plate as plate, seeds_read_cache as cache
from test_seeds_plate_projection import PROOF, fields, answer
from shantytown.owner_display_cache import display_reads


@pytest.fixture
def owner_wire(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path / 'cache'))
    monkeypatch.delenv('ST_SEEDS_READ_CACHE', raising=False)
    monkeypatch.setattr(cache, '_watermark', lambda *a: ('owner-fixture', 10))
    state = dict(queries=0, fail=False, title='actual work')
    mutex = threading.Lock()
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size):
            return json.dumps(answer(fields(title=state['title']))).encode()
    def send(request, timeout):
        with mutex:
            state['queries'] += 1
        time.sleep(.05)
        if state['fail']:
            raise ValueError('fixture refusal')
        return Response()
    monkeypatch.setattr(plate, 'urlopen', send)
    return state


def test_eight_display_owner_reads_share_one_complete_projection(owner_wire):
    # Count the actual native candidate/field requests, not a stubbed owner reader.
    plate.owner_rows(PROOF, 'worker').exact()
    per_projection = owner_wire['queries']
    cache.invalidate_stale()
    for entry in cache._directory().glob('read-*.json'):
        entry.unlink()
    owner_wire['queries'] = 0
    barrier = threading.Barrier(8)
    def read():
        with display_reads():
            barrier.wait(timeout=5)
            return plate.owner_rows(PROOF, 'worker').exact()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: read(), range(8)))
    assert all(rows[0]['title'] == 'actual work' for rows in results)
    assert owner_wire['queries'] == per_projection


def clear_exact_entries():
    for pattern in ('read-*.json', 'mark-*.json'):
        for entry in cache._directory().glob(pattern):
            entry.unlink()


@pytest.fixture
def sdk_write(tmp_path, monkeypatch):
    from shantytown import sd, actor_identity, advise_signing
    tracker = sd.SdTracker(repo=str(tmp_path), prefix='fixture')
    monkeypatch.setattr(tracker, 'prove_store', lambda: None)
    monkeypatch.setattr(tracker, '_location', lambda: [])
    monkeypatch.setattr(type(tracker), '_bin', property(lambda _: 'fixture-sdk'))
    monkeypatch.setattr(actor_identity, 'config_environment', lambda: {})
    monkeypatch.setattr(actor_identity, 'authenticated_actor', lambda: None)
    monkeypatch.setattr(advise_signing, 'mutation', lambda _: False)
    def write(*args, status=0, timeout=False):
        def runner(cmd, **kw):
            if timeout:
                raise subprocess.TimeoutExpired(cmd, 1)
            return subprocess.CompletedProcess(cmd, status, '{}', '')
        monkeypatch.setattr(sd.subprocess, 'run', runner)
        return tracker._bd(*args)
    return write


# Adapter-test admission: sdk_write replaces the runner before any call, so
# these exercise the real dispatch seam without reaching an executable/store.
@pytest.mark.real_store
@pytest.mark.parametrize('operation', ['send', 'read'])
def test_message_window_writes_keep_owner_display_but_invalidate_other_stale_reads(
        owner_wire, sdk_write, operation):
    with display_reads():
        plate.owner_rows(PROOF, 'worker').exact()
        _, publish = cache.stale_lookup(['generic-read'], lambda x: x)
        publish('old mailbox')
    before = owner_wire['queries']
    clear_exact_entries()
    sdk_write('msg', operation, '--json')
    with display_reads():
        assert cache.stale_lookup(['generic-read'], lambda x: x)[0] is None
        plate.owner_rows(PROOF, 'worker').exact()
    assert owner_wire['queries'] == before


@pytest.mark.real_store
@pytest.mark.parametrize('args', [('update', 'fixture-1'), ('msg', 'unknown-future-write')])
def test_board_and_unknown_writes_still_invalidate_owner_display(owner_wire, sdk_write, args):
    with display_reads():
        plate.owner_rows(PROOF, 'worker').exact()
    clear_exact_entries()
    owner_wire['title'] = 'written board value'
    sdk_write(*args)
    with display_reads():
        assert plate.owner_rows(PROOF, 'worker').exact()[0]['title'] == 'written board value'


@pytest.mark.real_store
@pytest.mark.parametrize('timeout', [False, True])
def test_failed_or_uncertain_message_writes_still_invalidate_owner_display(
        owner_wire, sdk_write, timeout):
    with display_reads():
        plate.owner_rows(PROOF, 'worker').exact()
    clear_exact_entries()
    owner_wire['title'] = 'after uncertain operation'
    if timeout:
        with pytest.raises(subprocess.TimeoutExpired):
            sdk_write('msg', 'send', timeout=True)
    else:
        assert sdk_write('msg', 'send', status=3).returncode == 3
    with display_reads():
        assert plate.owner_rows(PROOF, 'worker').exact()[0]['title'] == 'after uncertain operation'


def test_display_hit_own_write_invalidation_and_exact_admission(owner_wire):
    with display_reads():
        assert plate.owner_rows(PROOF, 'worker').exact()[0]['title'] == 'actual work'
    before = owner_wire['queries']
    clear_exact_entries()
    owner_wire['title'] = 'changed'
    with display_reads():
        assert plate.owner_rows(PROOF, 'worker').exact()[0]['title'] == 'actual work'
        assert owner_wire['queries'] == before
        with cache.exact_reads():
            assert plate.owner_rows(PROOF, 'worker').exact()[0]['title'] == 'changed'
    cache.invalidate_stale()
    clear_exact_entries()
    with display_reads():
        assert plate.owner_rows(PROOF, 'worker').exact()[0]['title'] == 'changed'
    assert owner_wire['queries'] > before


def test_plain_stale_scope_does_not_opt_decisions_into_owner_display(owner_wire):
    with display_reads():
        plate.owner_rows(PROOF, 'worker').exact()
    clear_exact_entries()
    owner_wire['title'] = 'fresh decision'
    with cache.stale_ok():
        assert plate.owner_rows(PROOF, 'worker').exact()[0]['title'] == 'fresh decision'


def test_failed_owner_cohort_is_incomplete_and_never_cached_empty(owner_wire):
    owner_wire['fail'] = True
    barrier = threading.Barrier(8)
    def read():
        with display_reads():
            barrier.wait(timeout=5)
            return plate.owner_rows(PROOF, 'worker')
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: read(), range(8)))
    assert all(not row.complete and row.caveat for row in results)
    assert owner_wire['queries'] == 1
    owner_wire['fail'] = False
    time.sleep(1.05)
    with display_reads():
        assert plate.owner_rows(PROOF, 'worker').exact()[0]['id'] == 'test-held'


def test_owner_flags_and_graph_are_distinct(owner_wire):
    from dataclasses import replace
    with display_reads():
        plate.owner_rows(PROOF, 'worker').exact()
        clear_exact_entries()
        before = owner_wire['queries']
        plate.owner_rows(PROOF, 'worker', decision=True).exact()
        assert owner_wire['queries'] > before
        # The fixture returns only PROOF's graph. A different graph must
        # refuse the fixture rather than borrow the populated cached answer.
        assert not plate.owner_rows(replace(PROOF, graph=PROOF.graph + '-other'),
                                    'worker').complete


def test_disabled_display_tier_reads_current_fields(owner_wire, monkeypatch):
    with display_reads():
        plate.owner_rows(PROOF, 'worker').exact()
    clear_exact_entries()
    owner_wire['title'] = 'after rollback'
    monkeypatch.setenv('ST_SEEDS_STALE_TTL', '0')
    with display_reads():
        assert plate.owner_rows(PROOF, 'worker').exact()[0]['title'] == 'after rollback'


def test_own_write_during_projection_prevents_display_publication(owner_wire, monkeypatch):
    original = plate._project_fields
    once = []
    def overlap(*args, **kwargs):
        result = original(*args, **kwargs)
        if not once:
            once.append(True)
            cache.invalidate_stale()
        return result
    monkeypatch.setattr(plate, '_project_fields', overlap)
    with display_reads():
        plate.owner_rows(PROOF, 'worker').exact()
    clear_exact_entries()
    owner_wire['title'] = 'post-write observation'
    with display_reads():
        assert plate.owner_rows(PROOF, 'worker').exact()[0]['title'] == 'post-write observation'


def test_custom_shape_guard_is_never_borrowed_from_a_display_hit(owner_wire):
    class Guard:
        calls = 0
        def check(self, *args, **kwargs):
            self.calls += 1
            return False
    guard = Guard()
    with display_reads():
        plate.owner_rows(PROOF, 'worker').exact()
        assert not plate.owner_rows(PROOF, 'worker', shape_reads=guard).complete
    assert guard.calls == 1


def test_cli_display_plate_enters_scope_for_lazy_reads(owner_wire, monkeypatch):
    from types import SimpleNamespace
    from shantytown import cli, br
    monkeypatch.setattr(cli, '_backend', lambda a: 'seeds')
    monkeypatch.setattr(br, 'plate_reader', lambda *a, **kw:
                        lambda who: plate.owner_rows(PROOF, who).exact())
    a = SimpleNamespace()
    first = cli._plate(a, tracker=object(), snapshot=True, display=True)('worker')
    before = owner_wire['queries']
    clear_exact_entries()
    assert cli._plate(a, tracker=object(), snapshot=True, display=True)('worker') == first
    assert owner_wire['queries'] == before
    owner_wire['title'] = 'fresh non-display'
    assert cli._plate(a, tracker=object(), snapshot=True)('worker')[0]['title'] == 'fresh non-display'


def test_equivalent_keyword_order_shares_the_same_host_key(owner_wire):
    with display_reads():
        first = plate.owner_rows(PROOF, 'worker', decision=True, include_deferred=True).exact()
        before = owner_wire['queries']
        clear_exact_entries()
        assert plate.owner_rows(PROOF, 'worker', include_deferred=True, decision=True).exact() == first
        assert owner_wire['queries'] == before
