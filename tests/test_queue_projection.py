import pytest
from shantytown import seeds_plate
from shantytown.sd import StoreProof

G = 'https://example.test/project/test'
PROOF = StoreProof('--quipu', None, 'https://example.test', 'test', G)


def wire(rows):
    return {'rows': rows, 'count': len(rows), 'truncated': False}


def test_queue_projection_is_capped_and_selects_indexed_lane_first(monkeypatch):
    calls = []
    def query(proof, text, timeout):
        calls.append(text)
        return wire([])
    monkeypatch.setattr(seeds_plate, '_query', query)
    assert seeds_plate.queue_rows(PROOF).exact() == []
    assert len(calls) == 1 and 'LIMIT 46' in calls[0]
    assert calls[0].index('ontology/lane') < calls[0].index('a <https://schema.org/Action>')
    assert '#seeds-ephemeral' in calls[0]


def test_queue_projection_missing_hydration_and_overcap_stay_unknown(monkeypatch):
    monkeypatch.setattr(seeds_plate, '_query', lambda *a: wire([
        {'subject': seeds_plate.SEEDS + 'item/test-1', 'graph': G}]))
    monkeypatch.setattr(seeds_plate, '_project_fields', lambda *a, **kw: {})
    with pytest.raises(Exception, match='incomplete'):
        seeds_plate.queue_rows(PROOF).exact()
    monkeypatch.setattr(seeds_plate, '_query', lambda *a: wire([{}] * 46))
    with pytest.raises(Exception, match='cap'):
        seeds_plate.queue_rows(PROOF).exact()
