"""Short watermark retries retain the cap, shared budget and fail-closed proof."""
import json,time
from urllib.error import URLError
import pytest
from shantytown import seeds_read_cache as cache

class Response:
    status=200
    def __enter__(self):return self
    def __exit__(self,*a):pass
    def read(self,size):return json.dumps(dict(store_id='store',watermark_tx=10)).encode()

@pytest.mark.parametrize('wrapped',[False,True])
@pytest.mark.parametrize('cap',[1,30])
def test_short_watermark_timeout_recovers_without_widening_cap(monkeypatch,wrapped,cap):
    calls=[];sleeps=[]
    def send(request,timeout):
        calls.append(timeout)
        if len(calls)==1:
            error=TimeoutError('fixture short read')
            raise URLError(error) if wrapped else error
        return Response()
    monkeypatch.setattr(cache.time,'sleep',sleeps.append)
    budget=dict(remaining=2,deadline=time.monotonic()+90)
    with cache.projection_reads(budget):
        assert cache._watermark('https://example.test',cap,send)==('store',10)
    assert calls==[min(cap,2)]*2
    assert sleeps==[.1]
    assert budget['remaining']==1

def test_watermark_recovery_cannot_add_an_unbounded_inner_retry(monkeypatch):
    calls=[];sleeps=[]
    def send(request,timeout):calls.append(timeout);raise TimeoutError('still unavailable')
    monkeypatch.setattr(cache.time,'sleep',sleeps.append)
    budget=dict(remaining=2,deadline=time.monotonic()+90)
    with cache.projection_reads(budget),pytest.raises(TimeoutError):
        cache._watermark('https://example.test',30,send)
    assert calls==[2,2,2]
    assert sleeps==[.1,.2]
    assert budget['remaining']==0

def test_non_timeout_failure_is_never_a_retry_permission(monkeypatch):
    calls=[]
    def send(request,timeout):calls.append(timeout);raise ValueError('malformed proof')
    budget=dict(remaining=2,deadline=time.monotonic()+90)
    with cache.projection_reads(budget),pytest.raises(ValueError,match='malformed'):
        cache._watermark('https://example.test',30,send)
    assert calls==[2]
    assert budget['remaining']==2

def test_ordinary_single_query_keeps_its_existing_timeout_refusal():
    calls=[]
    def send(request,timeout):calls.append(timeout);raise TimeoutError('no projection')
    with pytest.raises(TimeoutError):cache._watermark('https://example.test',30,send)
    assert calls==[2]

def test_expired_projection_never_starts_another_watermark_call():
    calls=[]
    def send(request,timeout):calls.append(timeout);return Response()
    budget=dict(remaining=2,deadline=time.monotonic()-1)
    with cache.projection_reads(budget),pytest.raises(ValueError,match='time budget'):
        cache._watermark('https://example.test',30,send)
    assert not calls


def test_recovery_tokens_cannot_be_reused_for_an_extra_entity_repair(monkeypatch):
    calls=[]
    def send(request,timeout):
        calls.append(timeout)
        if len(calls)<3:raise TimeoutError('brief writer pressure')
        return Response()
    monkeypatch.setattr(cache.time,'sleep',lambda delay:None)
    budget=dict(remaining=2,deadline=time.monotonic()+90)
    with cache.projection_reads(budget):
        assert cache._watermark('https://example.test',30,send)==('store',10)
        with pytest.raises(ValueError,match='retry budget'):
            cache.repair_entities(cache.EntityChanges({'urn:test'},('store',10)))
    assert len(calls)==3


def test_unreadable_url_error_is_not_a_timeout_retry(monkeypatch):
    calls=[]
    def send(request,timeout):calls.append(timeout);raise URLError('not a timeout')
    budget=dict(remaining=2,deadline=time.monotonic()+90)
    with cache.projection_reads(budget),pytest.raises(URLError):
        cache._watermark('https://example.test',30,send)
    assert len(calls)==1
    assert budget['remaining']==2
