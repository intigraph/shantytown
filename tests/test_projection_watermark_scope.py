"""Scope-local reuse keeps post-query proof and never hides write/failure boundaries."""
import json
import time
from urllib.parse import parse_qs, urlsplit

import pytest
from shantytown import seeds_read_cache as cache

SERVER = 'https://example.test'
GRAPH = 'urn:fixture:graph'
ENTITY = 'urn:fixture:item'


@pytest.fixture
def wire(monkeypatch, tmp_path):
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path / 'cache'))
    monkeypatch.delenv('ST_SEEDS_READ_CACHE', raising=False)
    state = dict(tx=10, store='fixture', requests=[], fetches=0, records=[], error=None)

    class Response:
        status = 200
        def __init__(self, data): self.data = data
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size): return json.dumps(self.data).encode()

    def send(request, timeout):
        path = urlsplit(request.full_url).path
        state['requests'].append(path)
        if path == '/watermark':
            if state['error'] is not None: raise state['error']
            return Response(dict(store_id=state['store'], watermark_tx=state['tx']))
        assert path == '/changes'
        since = int(parse_qs(urlsplit(request.full_url).query)['since'][0])
        records = [r for r in state['records'] if r['tx'] > since]
        return Response(dict(since=since, records=records,
            next_tx=max((r['tx'] for r in records), default=since),
            watermark_tx=state['tx'], capture='new_values',
            source=dict(store_id=state['store'], log_epoch='epoch')))

    def read(query):
        def fetch():
            state['fetches'] += 1
            return {'value': state['tx']}
        return cache.read(SERVER, query, 2, opener=send, fetch=fetch, validate=lambda v: v)

    def certify():
        cache.certify_projection(SERVER, [GRAPH], {ENTITY}, {'urn:fixture:owner'}, 2, send)

    return state, read, certify


def test_n_reads_use_one_watermark_including_final_certification(wire):
    state, read, certify = wire
    with cache.projection_reads():
        for i in range(5): assert read(str(i)) == {'value': 10}
        certify()
    assert state['requests'].count('/watermark') == 1
    assert state['requests'].count('/changes') == 1
    assert state['fetches'] == 5


def test_two_scopes_observe_twice_even_with_warm_shared_cache(wire):
    state, read, certify = wire
    for _ in range(2):
        with cache.projection_reads():
            read('same-query')
            certify()
    assert state['requests'].count('/watermark') == 2
    assert state['requests'].count('/changes') == 2
    assert state['fetches'] == 1  # Result caching remains useful; mark reuse does not cross scopes.


@pytest.mark.parametrize('cache_unavailable', [False, True])
def test_write_invalidation_refuses_scope_even_without_cache_directory(wire, monkeypatch, cache_unavailable):
    state, read, certify = wire
    with cache.projection_reads():
        read('before')
        if cache_unavailable:
            monkeypatch.setattr(cache, '_directory', lambda: (_ for _ in ()).throw(OSError('offline')))
        cache.invalidate_stale()
        with pytest.raises(ValueError, match='invalidated'): read('after')
        with pytest.raises(ValueError, match='invalidated'): certify()
    assert state['fetches'] == 1
    assert state['requests'] == ['/watermark']


@pytest.mark.parametrize('error', [ValueError('bad watermark'), TimeoutError('timed out')])
def test_failed_mark_cannot_be_retried_as_success_in_same_scope(wire, error):
    state, read, certify = wire
    state['error'] = error
    with cache.projection_reads():
        with pytest.raises(type(error)): read('first')
        state['error'] = None
        with pytest.raises(type(error)): read('second')
        with pytest.raises(type(error)): certify()
    assert state['fetches'] == 0
    assert state['requests'] == ['/watermark']


def test_timeout_retries_keep_shared_budget_then_poison_scope(wire, monkeypatch):
    state, read, certify = wire
    state['error'] = TimeoutError('timed out')
    monkeypatch.setattr(cache.time, 'sleep', lambda _: None)
    budget = dict(remaining=2, deadline=time.monotonic() + 20)
    with cache.projection_reads(budget):
        with pytest.raises(TimeoutError): read('first')
        with pytest.raises(TimeoutError): read('second')
    assert budget['remaining'] == 0
    assert state['requests'] == ['/watermark'] * 3


def test_final_proof_detects_payload_write_without_second_watermark(wire):
    state, read, certify = wire
    with cache.projection_reads():
        read('before')
        state['tx'] = 11
        state['records'] = [dict(tx=11, graph=GRAPH, entity=ENTITY,
                                attribute='urn:fixture:title', op='assert')]
        with pytest.raises(cache.EntityChanges): certify()
    assert state['requests'] == ['/watermark', '/changes']
    assert not list(cache._directory().glob('read-*.json'))


def test_final_proof_detects_store_replacement(wire):
    state, read, certify = wire
    with cache.projection_reads():
        read('before')
        state['store'] = 'replacement'
        with pytest.raises(cache.StoreChanged): certify()
    assert state['requests'] == ['/watermark', '/changes']


def test_scope_cannot_share_mark_with_another_server(wire):
    state, read, certify = wire
    with cache.projection_reads():
        read('before')
        with pytest.raises(ValueError, match='across servers'):
            cache._watermark('https://other.example.test', 2, lambda *a, **kw: pytest.fail('sent'))
        with pytest.raises(ValueError): certify()


def test_after_invalidation_only_a_new_scope_can_observe_post_write(wire):
    state, read, certify = wire
    with cache.projection_reads():
        read('same')
        state['tx'] = 11
        cache.invalidate_stale()
        with pytest.raises(ValueError, match='invalidated'): read('same')
    with cache.projection_reads():
        assert read('same') == {'value': 11}
        certify()
    assert state['requests'].count('/watermark') == 2


def test_write_during_fetch_refuses_before_returning_a_result(wire):
    state, read, certify = wire
    def fetch():
        cache.invalidate_stale()
        return {'value': 'pre-write'}
    with cache.projection_reads():
        read('initial')
        with pytest.raises(ValueError, match='invalidated'):
            cache.read(SERVER, 'write-during-fetch', 2,
                       opener=lambda *a, **kw: pytest.fail('unexpected mark'),
                       fetch=fetch, validate=lambda v: v)


def test_nested_scope_write_also_invalidates_outer_scope(wire):
    state, read, certify = wire
    with cache.projection_reads():
        read('outer')
        with cache.projection_reads():
            read('inner')
            cache.invalidate_stale()
        with pytest.raises(ValueError, match='invalidated'): read('outer-again')
        with pytest.raises(ValueError, match='invalidated'): certify()
    assert state['requests'].count('/watermark') == 2


def test_certification_cannot_switch_servers(wire):
    state, read, certify = wire
    with cache.projection_reads():
        read('before')
        with pytest.raises(ValueError, match='across servers'):
            cache.certify_projection('https://other.example.test', [GRAPH], {ENTITY}, set(), 2,
                                     lambda *a, **kw: pytest.fail('sent'))
