from dataclasses import replace
import pytest
from shantytown import seeds_plate as p
from shantytown.sd import StoreProof


def test_positive_roster_guard_covers_only_same_store_and_roster(monkeypatch):
    calls = []
    monkeypatch.setattr(p, 'owner_shape_supported', lambda proof, scope, **kw: calls.append((proof, scope)) or True)
    proof = StoreProof('fixture', None, 'http://example.test', 'test', 'urn:graph')
    cache = p.RenderShapeReads()
    assert cache.check(proof, ('crew/a', 'b'), timeout=10)
    for _ in range(7):
        assert cache.check(proof, 'a', timeout=10)
        assert cache.check(proof, 'crew/b', timeout=10)
    assert len(calls) == 1
    assert cache.check(proof, 'c', timeout=10)
    assert cache.check(replace(proof, graph='urn:other'), 'a', timeout=10)
    assert cache.check(replace(proof, quipu_url='http://other.test'), 'a', timeout=10)
    assert len(calls) == 4
    assert p.RenderShapeReads().check(proof, 'a', timeout=10)
    assert len(calls) == 5


def test_refusal_exception_and_narrow_positive_cannot_prove_roster(monkeypatch):
    proof = StoreProof('fixture', None, 'http://example.test', 'test', 'urn:graph')
    cache = p.RenderShapeReads()
    calls = []
    def check(proof, scope, **kw):
        calls.append(scope)
        if scope == ('a', 'b'):
            return False
        if scope == 'error':
            raise OSError('read unavailable')
        return True
    monkeypatch.setattr(p, 'owner_shape_supported', check)
    assert not cache.check(proof, ('a', 'b'), timeout=10)
    assert cache.check(proof, 'a', timeout=10)
    assert not cache.check(proof, ('a', 'b'), timeout=10)
    assert cache.check(proof, 'a', timeout=10)
    for _ in range(2):
        with pytest.raises(OSError):
            cache.check(proof, 'error', timeout=10)
    assert len(calls) == 6
