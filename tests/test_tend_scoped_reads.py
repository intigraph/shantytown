"""Read metadata and caller identity preserve tend's uncertainty contract."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from shantytown import cli, seeds_plate
from shantytown.query_identity import declared_query_identity
from shantytown.sd import StoreProof

G = 'https://example.test/project/test'
PROOF = StoreProof('--quipu', None, 'https://example.test', 'test', G)
NOW = datetime(2026, 1, 2, tzinfo=timezone.utc)


def row(id, **fields):
    return dict({'subject': seeds_plate.SEEDS + 'item/' + id, 'graph': G, 'id': id}, **fields)


def wire(monkeypatch, rows):
    monkeypatch.setattr(seeds_plate, '_query', lambda *a: dict(rows=rows, count=len(rows), truncated=False))


def test_count_preserves_messages_and_defer_boundaries(monkeypatch):
    wire(monkeypatch, [row('test-message'), row('test-work'),
                      row('test-due', due='2026-01-02T00:00:00Z'),
                      row('test-future', due='2026-01-02T00:00:01Z')])
    assert seeds_plate.ready_count(PROOF, now=NOW) == 3
    wire(monkeypatch, [])
    assert seeds_plate.ready_count(PROOF, now=NOW) == 0


@pytest.mark.parametrize('fault', [dict(due='bad'), dict(due='2026-01-02'),
                                    dict(due='2026-01-02T00:00:00Z', legacy_due='2026-01-03T00:00:00Z'),
                                    dict(subject='https://example.test/foreign'), dict(graph=G+'foreign')])
def test_malformed_count_is_unknown(monkeypatch, fault):
    wire(monkeypatch, [row('test-work', **fault)])
    with pytest.raises(ValueError):
        seeds_plate.ready_count(PROOF, now=NOW)


def test_shadowed_id_is_unknown(monkeypatch):
    wire(monkeypatch, [row('test-work'), row('test-work', graph=G+'#seeds-ephemeral')])
    with pytest.raises(ValueError, match='ambiguous'):
        seeds_plate.ready_count(PROOF, now=NOW)


def test_tend_context_declares_read_caller_preserves_write_actor(monkeypatch):
    monkeypatch.setenv('QUIPU_AGENT', 'worker')
    monkeypatch.setenv('SHANTY_AGENT', 'worker')
    monkeypatch.setenv('SEEDS_ACTOR', 'operator')
    seen = []
    monkeypatch.setattr(cli, '_tend_status', lambda a: seen.append(__import__('os').environ['QUIPU_AGENT']) or 0)
    assert cli._cmd_tend(SimpleNamespace(retire=False, unretire=False, install=False, uninstall=False, status=True)) == 0
    import os
    assert seen == ['st-tend']
    assert os.environ['QUIPU_AGENT'] == 'worker'
    assert os.environ['SHANTY_AGENT'] == 'worker'
    assert os.environ['SEEDS_ACTOR'] == 'operator'


def test_identity_restored_on_error(monkeypatch):
    monkeypatch.delenv('QUIPU_AGENT', raising=False)
    with pytest.raises(ValueError), declared_query_identity('st-tend'):
        raise ValueError('failed read')
    import os
    assert 'QUIPU_AGENT' not in os.environ


def test_native_header_matches_sdk_service_identity(monkeypatch):
    seen = []
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self, size): return json.dumps(dict(rows=[], count=0, truncated=False)).encode()
    monkeypatch.setattr(seeds_plate, 'urlopen', lambda request, timeout: seen.append(request.get_header('X-quipu-agent')) or Response())
    monkeypatch.setenv('SEEDS_AGENT_NAME', 'worker')
    with declared_query_identity('st-tend'):
        seeds_plate.ready_count(PROOF, now=NOW)
    assert seen == ['st-tend']


def test_active_projection_is_owner_scoped_not_open_unassigned(monkeypatch):
    from shantytown.sd import SdTracker
    tracker = SdTracker(quipu=PROOF.quipu_url, prefix='test')
    monkeypatch.setattr(tracker, 'prove_store', lambda: PROOF)
    monkeypatch.setattr(seeds_plate, 'uses_native_schema', lambda *a, **k: True)
    monkeypatch.setattr(seeds_plate, 'owner_shape_supported', lambda *a, **k: True)
    base = dict(id='test-active', title='work', status='in_progress', assignee='worker', priority=1, created_at='2026-01-01T00:00:00Z')
    inverse = {v:k for k,v in seeds_plate.FIELDS.items()}
    fields = [dict(subject=seeds_plate.SEEDS+'item/test-active', graph=G, predicate=inverse[k], value=v) for k,v in base.items()]
    seen = []
    monkeypatch.setattr(seeds_plate, '_query', lambda p,q,t: seen.append(q) or dict(rows=fields, count=len(fields), truncated=False))
    assert tracker.active_rows(['worker'])[0]['id'] == 'test-active'
    assert '"in_progress"' in seen[0] and '"open"' not in seen[0]
    assert 'FILTER(STR(?owner) != "")' not in seen[0]


def test_active_barrier_is_fresh_on_every_call(monkeypatch):
    from shantytown import feed_check
    from shantytown.sd import SdTracker
    from shantytown.answer import Answer
    tracker = SdTracker(quipu=PROOF.quipu_url, prefix='test')
    reg = SimpleNamespace(all=lambda: Answer.complete_read([SimpleNamespace(name='worker',role='worker')], how='fixture'))
    calls = []
    monkeypatch.setattr(feed_check, '_br_tracker', lambda *a: tracker)
    monkeypatch.setattr(tracker, 'active_rows', lambda owners: calls.append(owners) or [{'id': 'test-'+str(len(calls))}])
    assert feed_check.tend_active(None,reg) == [{'id':'test-1'}]
    assert feed_check.tend_active(None,reg) == [{'id':'test-2'}]
    assert calls == [['worker'], ['worker']]


def test_projection_failure_never_falls_back_to_legacy(monkeypatch):
    from shantytown import feed_check
    from shantytown.sd import SdTracker
    from shantytown.answer import Answer
    tracker = SdTracker(quipu=PROOF.quipu_url, prefix='test')
    reg = SimpleNamespace(all=lambda: Answer.complete_read([], how='fixture'))
    monkeypatch.setattr(feed_check, '_br_tracker', lambda *a: tracker)
    monkeypatch.setattr(tracker, 'active_rows', lambda *a: (_ for _ in ()).throw(ValueError('unreadable')))
    monkeypatch.setattr(feed_check,'bd_in_progress', lambda *a, **k: pytest.fail('legacy fallback'))
    with pytest.raises(ValueError,match='unreadable'):
        feed_check.tend_active(None,reg)


def test_legacy_ready_reader_does_not_add_active_reads(monkeypatch):
    from shantytown import feed_check
    monkeypatch.setattr(feed_check, '_br_tracker', lambda *a: None)
    monkeypatch.setattr(feed_check, 'bd_cwd', lambda *a: None)
    monkeypatch.setattr(feed_check, '_bd_ready', lambda *a, **kw: [{'id':'test-ready'}])
    monkeypatch.setattr(feed_check, 'bd_in_progress', lambda *a, **kw: pytest.fail('unexpected active read'))
    assert feed_check.tend_ready(None,None,['worker']) == [{'id':'test-ready'}]


def test_tend_retains_priority_creation_id_order_and_missing_is_unknown():
    from shantytown.sd import SdTracker, StoreUnproven
    rows = [dict(id='test-new', priority=1, created_at='2026-01-02T00:00:00Z'),
            dict(id='test-old', priority=1, created_at='2026-01-01T00:00:00Z'),
            dict(id='test-urgent', priority=0, created_at='2026-01-02T00:00:00Z')]
    assert [r['id'] for r in SdTracker._tend_order(rows)] == ['test-urgent','test-old','test-new']
    with pytest.raises(StoreUnproven):
        SdTracker._tend_order([dict(id='test-missing',priority=0)])
