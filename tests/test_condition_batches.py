"""Candidate batches keep individual uncertainty and release freshness."""
import pytest
from shantytown import seeds_plate
from shantytown.sd import StoreProof

PROOF = StoreProof('--quipu', None, 'https://example.test', 'test', 'https://example.test/project/test')


def test_individual_unknown_does_not_hide_positive_controls(monkeypatch):
    rows = [
        dict(requested='test-closed', graph=PROOF.graph, id='test-closed', status='closed'),
        dict(requested='test-open', graph=PROOF.graph, id='test-open', status='open'),
        dict(requested='test-shadow', graph=PROOF.graph, id='test-shadow', status='closed'),
        dict(requested='test-shadow', graph=PROOF.graph+'#seeds-ephemeral', id='test-shadow', status='closed'),
        dict(requested='test-wrong', graph=PROOF.graph, id='test-other', status='closed'),
        dict(requested='test-bad', graph=PROOF.graph, id='test-bad', status='unsupported'),
    ]
    monkeypatch.setattr(seeds_plate, '_query', lambda *args: dict(rows=rows))
    assert seeds_plate.closed_statuses(PROOF, ['test-closed', 'test-open', 'test-shadow', 'test-wrong', 'test-bad', 'test-absent']) == {
        'test-closed': True, 'test-open': False, 'test-shadow': None,
        'test-wrong': None, 'test-bad': None, 'test-absent': None}


@pytest.mark.parametrize('failure', ['error', 'budget', 'unexpected'])
def test_failed_batch_never_authorizes_release_or_serial_retry(monkeypatch, failure):
    calls = []
    def query(*args):
        calls.append(args[1])
        if failure == 'error': raise OSError('unreadable')
        row = dict(requested='wrong-target', graph=PROOF.graph, id='wrong-target', status='closed')
        return dict(rows=[row] * (1000 if failure == 'budget' else 1))
    monkeypatch.setattr(seeds_plate, '_query', query)
    assert seeds_plate.closed_statuses(PROOF, ['test-one', 'test-two']) == {'test-one': None, 'test-two': None}
    assert len(calls) == 1


def test_failure_does_not_poison_next_batch_and_duplicates_cost_nothing(monkeypatch):
    calls = []
    def query(*args):
        calls.append(args[1])
        if len(calls) == 1: raise OSError('first chunk failed')
        return dict(rows=[dict(requested='test-25', graph=PROOF.graph, id='test-25', status='closed')])
    monkeypatch.setattr(seeds_plate, '_query', query)
    result = seeds_plate.closed_statuses(PROOF, [f'test-{i}' for i in range(26)] + ['test-25'])
    assert result['test-25'] is True
    assert all(result[f'test-{i}'] is None for i in range(25))
    assert len(calls) == 2
