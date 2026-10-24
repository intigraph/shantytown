import fcntl
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from shantytown import cost, cost_review as review, cost_sampling


def write(path, value):
    path.write_text(json.dumps(value))


@pytest.fixture
def population(tmp_path):
    state = tmp_path / review.LEGACY
    samples = [{'run': 81 + n, 'attempted_at': 1000 + n, 'items': 1,
                'records': 10 + n, 'body_bytes': 100 + n} for n in range(20)]
    write(state, {'snapshots': {'session': {'source_hash': 'previous'}}})
    write(state.with_suffix('.budget.json'), {
        'runs': 100, 'samples': samples, 'distinct_samples': samples,
        'distinct_shapes': 20, 'distinct_shapes_saturated': True, 'review_due': True,
        'review_window_started_at': 900, 'max_items': 15, 'max_records': 797,
        'refusal_accounting': {'attempts': 81, 'refusals': 3}})
    write(state.with_suffix('.receipt.json'), {'status': 'OK', 'attempted_at': 1200,
                                             'next_request_after': 9999999999})
    write(tmp_path / 'cost-active-rotation.json', {
        'last': ['worker', 'session'], 'samples': [
            {**s, 'source': {'agent': 'worker', 'harness': 'codex',
                            'session': 'session', 'path': '/synthetic/transcript'}} for s in samples]})
    write(tmp_path / 'cost-active-review.json', {'status': 'REVIEW_DUE'})
    write(tmp_path / 'cost.json', {'sample_active_sources': True})
    (tmp_path / 'cost.lock').touch()
    return tmp_path


def decision(digest):
    return {'schema_version': 1, 'window_sha256': digest, 'decision': 'accept',
            'mode': 'bounded-pilot', 'reviewer': 'reviewer',
            'evidence_ref': 'https://tracker.example/item/review#decision'}


def files(root):
    return {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in root.rglob('*') if p.is_file()}


def arguments(root, **kw):
    return SimpleNamespace(root=root, sync=False, bead=None, json=True,
                           review_window=not bool(kw.get('accept_window')),
                           accept_window=kw.get('accept_window'),
                           decision_file=kw.get('decision_file'), execute=kw.get('execute', False))


def test_manifest_is_read_only_and_ignores_heartbeat_not_cooldown(population):
    before = files(population)
    original = review.window(population)
    assert files(population) == before
    receipt = population / 'cost-active-graph-state.receipt.json'
    write(receipt, {'status': 'UNKNOWN', 'attempted_at': 9999, 'requests': 0,
                    'next_request_after': 9999999999})
    assert review.window(population) == original
    write(receipt, {'next_request_after': 9999999998})
    assert review.window(population)['window_sha256'] != original['window_sha256']


@pytest.mark.parametrize('field', ['samples', 'source', 'snapshot', 'limits'])
def test_digest_binds_the_reviewed_preimage(population, monkeypatch, field):
    before = review.window(population)['window_sha256']
    if field == 'snapshot':
        write(population / review.LEGACY, {'snapshots': {'different': 'ledger'}})
    elif field == 'limits':
        monkeypatch.setattr(review, 'LIMITS', {**review.LIMITS, 'items': 9})
    elif field == 'source':
        p = population / 'cost-active-rotation.json'
        d = json.loads(p.read_text()); d['samples'][0]['source']['session'] = 'other'; write(p, d)
    else:
        p = population / 'cost-active-graph-state.budget.json'
        d = json.loads(p.read_text()); d['runs'] += 1; write(p, d)
    assert review.window(population)['window_sha256'] != before


@pytest.mark.parametrize('bad', ['missing-source', 'duplicate-source', 'duplicate-shape', 'non-finite'])
def test_incomplete_or_ambiguous_evidence_refuses(population, bad):
    if bad in {'missing-source', 'duplicate-source'}:
        p = population / 'cost-active-rotation.json'; d = json.loads(p.read_text())
        d['samples'] = d['samples'][:-1] if bad == 'missing-source' else d['samples'] + [d['samples'][0]]
    else:
        p = population / 'cost-active-graph-state.budget.json'; d = json.loads(p.read_text())
        if bad == 'duplicate-shape':
            d['distinct_samples'][1].update({k: d['distinct_samples'][0][k] for k in ('items', 'records', 'body_bytes')})
        else:
            d['distinct_samples'][0]['attempted_at'] = float('nan')
    write(p, d)
    with pytest.raises(ValueError):
        review.window(population)


def test_prepare_is_read_only_and_transition_preserves_predecessor_and_lifetime(population):
    before = files(population)
    manifest = review.window(population); digest = manifest['window_sha256']
    assert review.advance(population, digest, decision(digest))['status'] == 'READY'
    assert files(population) == before
    result = review.advance(population, digest, decision(digest), execute=True)
    assert result['status'] == 'ADVANCED' and result['published'] is False
    assert all(files(population)[k] == v for k, v in before.items())
    state = cost_sampling.state_path(population)
    assert state != population / review.LEGACY
    assert state.read_bytes() == before[review.LEGACY][0]
    budget = json.loads(state.with_suffix('.budget.json').read_text())
    assert budget['runs'] == 100 and budget['max_items'] == 15 and budget['max_records'] == 797
    assert budget['refusal_accounting'] == {'attempts': 81, 'refusals': 3}
    assert budget['distinct_samples'] == [] and budget['review_due'] is False
    assert json.loads(state.with_suffix('.receipt.json').read_text())['next_request_after'] == 9999999999
    assert cost_sampling.review(population) is None
    assert review.describe(population)['accepted_review']['window_sha256'] == digest
    after = files(population)
    with pytest.raises(ValueError, match='complete review-due'):
        review.advance(population, digest, decision(digest), execute=True)
    assert files(population) == after


@pytest.mark.parametrize('bad', ['stale', 'continuous', 'ruling', 'extra-field', 'bool-version'])
def test_unbound_or_wider_decision_never_changes_files(population, bad):
    digest = review.window(population)['window_sha256']; d = decision(digest)
    if bad == 'stale': d['window_sha256'] = '0' * 64
    if bad == 'continuous': d['mode'] = 'continuous'
    if bad == 'ruling': d['evidence_ref'] = ''
    if bad == 'extra-field': d['raise_caps'] = True
    if bad == 'bool-version': d['schema_version'] = True
    before = files(population)
    with pytest.raises(ValueError): review.advance(population, digest, d, execute=True)
    with pytest.raises(ValueError, match='hash mismatch'):
        review.advance(population, '0' * 64, decision('0' * 64), execute=True)
    assert files(population) == before


@pytest.mark.parametrize('name', ['cost-graph-state.pending.json', 'cost-active-graph-state.pending.json'])
@pytest.mark.parametrize('dangling', [False, True])
def test_pending_even_empty_or_dangling_never_resumes(population, name, dangling):
    p = population / name
    p.symlink_to(population / 'absent') if dangling else write(p, {})
    digest = review.window(population)['window_sha256']
    with pytest.raises(ValueError, match='pending'):
        review.advance(population, digest, decision(digest), execute=True)
    assert not (population / review.POINTER).exists()


def test_cli_uses_the_producer_lock_and_never_calls_sync(population, monkeypatch, capsys):
    monkeypatch.setattr(cost, '_run_locked', lambda *_: pytest.fail('entered publisher'))
    with (population / 'cost.lock').open() as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert cost.run(arguments(population)) == 2
    assert 'UNKNOWN' in capsys.readouterr().out
    before = files(population)
    assert cost.run(arguments(population)) == 0
    assert files(population) == before


def test_failed_pointer_commit_preserves_old_state_and_orphan(population, monkeypatch):
    digest = review.window(population)['window_sha256']; before = files(population)
    def fail(*_): raise OSError('synthetic rename failure')
    monkeypatch.setattr(review.os, 'replace', fail)
    with pytest.raises(OSError): review.advance(population, digest, decision(digest), execute=True)
    assert cost_sampling.state_path(population) == population / review.LEGACY
    assert all(files(population)[k] == v for k, v in before.items())
    assert (population / review.GENERATIONS / digest / 'review.json').exists()
    with pytest.raises(ValueError, match='pre-existing generation'):
        review.advance(population, digest, decision(digest), execute=True)


def test_lost_reply_after_commit_is_read_back_never_replayed(population, monkeypatch):
    digest = review.window(population)['window_sha256']; replace = review.os.replace
    def lost(*args): replace(*args); raise OSError('synthetic lost reply')
    monkeypatch.setattr(review.os, 'replace', lost)
    with pytest.raises(OSError): review.advance(population, digest, decision(digest), execute=True)
    assert review.describe(population)['accepted_review']['window_sha256'] == digest
    before = files(population)
    with pytest.raises(ValueError): review.advance(population, digest, decision(digest), execute=True)
    assert files(population) == before


@pytest.mark.parametrize('member', ['review.json', 'predecessor/budget.json'])
def test_archive_or_manifest_corruption_refuses_selection(population, member):
    digest = review.window(population)['window_sha256']
    review.advance(population, digest, decision(digest), execute=True)
    p = population / review.GENERATIONS / digest / member; p.write_bytes(p.read_bytes() + b' ')
    with pytest.raises(ValueError, match='hash differs'): cost_sampling.state_path(population)


def test_generation_symlink_cannot_redirect_an_archive(population, tmp_path):
    outside = tmp_path / 'outside'; outside.mkdir()
    (population / review.GENERATIONS).symlink_to(outside, target_is_directory=True)
    digest = review.window(population)['window_sha256']
    with pytest.raises(ValueError): review.advance(population, digest, decision(digest), execute=True)
    assert list(outside.iterdir()) == []


def test_changed_preimage_during_preparation_refuses_commit(population, monkeypatch):
    digest = review.window(population)['window_sha256']; original = review._sync_dir
    def changed(path):
        original(path)
        if Path(path).name == review.GENERATIONS:
            write(population / review.LEGACY, {'snapshots': {'changed': 'concurrent writer'}})
    monkeypatch.setattr(review, '_sync_dir', changed)
    with pytest.raises(ValueError, match='evidence changed'):
        review.advance(population, digest, decision(digest), execute=True)
    assert not (population / review.POINTER).exists()


def test_successor_cannot_hide_legacy_pending_or_cooldown(population, monkeypatch):
    digest = review.window(population)['window_sha256']
    review.advance(population, digest, decision(digest), execute=True)
    config = json.loads((population / 'cost.json').read_text());config['publish_script'] = 'synthetic'
    write(population / 'cost.json', config)
    monkeypatch.setattr(cost, '_scheduler_status', lambda *_: None)
    monkeypatch.setattr(cost, '_publish_metrics', lambda *_args, **_kw: None)
    monkeypatch.setattr(cost_sampling, 'select', lambda *_: pytest.fail('cooldown/pending bypassed'))
    a = arguments(population);a.review_window = False;a.sync = True
    assert cost.run(a) == 0  # carried cooldown blocks before source selection
    (population / 'cost-active-graph-state.pending.json').symlink_to(population / 'absent')
    assert cost.run(a) == 2


def test_cli_execution_and_readback_do_not_touch_predecessors(population, capsys):
    digest = review.window(population)['window_sha256']
    p = population / 'decision.json';write(p, decision(digest))
    before = files(population)
    a = arguments(population, accept_window=digest, decision_file=str(p))
    assert cost.run(a) == 0 and 'READY' in capsys.readouterr().out
    assert files(population) == before
    a.execute = True
    assert cost.run(a) == 0 and 'ADVANCED' in capsys.readouterr().out
    assert cost.run(arguments(population)) == 0
    status = json.loads(capsys.readouterr().out)
    assert status['status'] == 'SAMPLING' and status['window_samples'] == 0
    assert status['accepted_review']['window_sha256'] == digest


def test_invalid_pointer_fails_closed_instead_of_legacy_fallback(population):
    write(population / review.POINTER, {'schema_version': 1, 'generation': '../foreign'})
    with pytest.raises(ValueError, match='invalid cost generation pointer'):
        cost_sampling.state_path(population)


def test_decision_flags_cannot_fall_through_to_the_parser(population, monkeypatch):
    monkeypatch.setattr(cost, '_run_locked', lambda *_: pytest.fail('entered publisher'))
    a = arguments(population);a.review_window = False;a.execute = True
    assert cost.run(a) == 2


@pytest.mark.parametrize('name', ['cost.lock', 'cost-active-graph-state.budget.json'])
def test_fifo_evidence_cannot_block_a_bounded_review(population, name):
    p = population / name;p.unlink();os.mkfifo(p)
    assert cost.run(arguments(population)) == 2


def next_window(root, *, oversized=False):
    state = review.state_path(root)
    old = json.loads(state.with_suffix('.budget.json').read_text())
    samples = [{'run': old['runs'] + n + 1, 'attempted_at': 3000 + old['runs'] + n,
                'items': 9 if oversized and n == 0 else 1,
                'records': 20 + n, 'body_bytes': 200 + n} for n in range(20)]
    old.update(runs=old['runs'] + 20, samples=samples, distinct_samples=samples,
               review_due=True, distinct_shapes=20, distinct_shapes_saturated=True)
    write(state.with_suffix('.budget.json'), old)
    write(root / 'cost-active-rotation.json', {'last': ['worker', 'session'], 'samples': [
        {**s, 'source': {'agent': 'worker', 'harness': 'codex',
                        'session': 'session', 'path': '/synthetic/transcript'}} for s in samples]})
    return state


def test_continuous_policy_archives_without_lifetime_or_ledger_reset(population):
    digest = review.window(population)['window_sha256']
    policy = {**decision(digest), 'mode': 'bounded-continuous'}
    review.advance(population, digest, policy, execute=True)
    previous = next_window(population)
    saved = {p: p.read_bytes() for p in previous.parent.rglob('*') if p.is_file()}
    assert review.rollover(population) is True
    state = review.state_path(population)
    assert state != previous and all(p.read_bytes() == raw for p, raw in saved.items())
    history = json.loads(state.with_suffix('.budget.json').read_text())
    assert history['runs'] == 120 and history['max_items'] == 15
    assert history['refusal_accounting'] == {'attempts': 81, 'refusals': 3}
    assert history['distinct_samples'] == [] and not history['review_due']
    assert state.read_bytes() == previous.read_bytes()
    receipt = json.loads(state.with_suffix('.receipt.json').read_text())
    assert receipt['next_request_after'] == 9999999999 and receipt['status'] == 'UNKNOWN'


def test_pilot_does_not_auto_accept_its_next_window(population):
    digest = review.window(population)['window_sha256']
    review.advance(population, digest, decision(digest), execute=True)
    next_window(population)
    before = files(population)
    assert review.rollover(population) is False
    assert files(population) == before


@pytest.mark.parametrize('blocked', ['oversized', 'pending', 'manifest', 'orphan'])
def test_continuous_rollover_preserves_refusals_and_uncertainty(population, blocked):
    digest = review.window(population)['window_sha256']
    review.advance(population, digest, {**decision(digest), 'mode': 'bounded-continuous'}, execute=True)
    state = next_window(population, oversized=blocked == 'oversized')
    if blocked == 'pending': state.with_suffix('.pending.json').write_text('{}')
    if blocked == 'manifest':
        p = state.parent / 'review.json'; p.write_bytes(p.read_bytes() + b' ')
    if blocked == 'orphan':
        folder = population / review.GENERATIONS / review.window(population)['window_sha256']
        folder.mkdir()
    before = files(population)
    if blocked == 'oversized': assert review.rollover(population) is False
    else:
        with pytest.raises(ValueError): review.rollover(population)
    assert files(population) == before


def test_mutable_history_cannot_enable_continuous_mode(population):
    digest = review.window(population)['window_sha256']
    review.advance(population, digest, decision(digest), execute=True)
    state = next_window(population)
    history = json.loads(state.with_suffix('.budget.json').read_text())
    history['accepted_review']['mode'] = 'bounded-continuous'
    write(state.with_suffix('.budget.json'), history)
    assert review.rollover(population) is False


def test_continuous_policy_survives_second_roll_and_never_replays(population):
    digest = review.window(population)['window_sha256']
    review.advance(population, digest, {**decision(digest), 'mode': 'bounded-continuous'}, execute=True)
    first = next_window(population)
    review.rollover(population)
    second = next_window(population)
    assert review.rollover(population) is True
    assert review.describe(population)['lifetime_runs'] == 140
    assert first.exists() and second.exists()
    before = files(population)
    with pytest.raises(ValueError, match='no complete'):
        review.rollover(population)
    assert files(population) == before


def test_scheduler_rolls_under_existing_lock_then_obeys_cooldown(population, monkeypatch):
    digest = review.window(population)['window_sha256']
    review.advance(population, digest, {**decision(digest), 'mode': 'bounded-continuous'}, execute=True)
    old = next_window(population)
    write(population / 'cost.json', {'sample_active_sources': True, 'publish_script': 'synthetic'})
    monkeypatch.setattr(cost, '_scheduler_status', lambda *_: None)
    monkeypatch.setattr(cost, '_publish_metrics', lambda *_args, **_kw: None)
    monkeypatch.setattr(cost, '_run_selected', lambda *_: pytest.fail('cooldown bypassed'))
    monkeypatch.setattr(cost_sampling, 'select', lambda *_: pytest.fail('selected during cooldown'))
    assert cost.run(SimpleNamespace(root=population, sync=True, bead=None)) == 0
    assert review.state_path(population) != old
    assert review.describe(population)['lifetime_runs'] == 120


def test_rotation_prunes_only_previously_archived_source_evidence(population):
    digest = review.window(population)['window_sha256']
    review.advance(population, digest, {**decision(digest), 'mode': 'bounded-continuous'}, execute=True)
    state = review.state_path(population)
    sample = {'run': 101, 'attempted_at': 5000, 'items': 1, 'records': 2, 'body_bytes': 3}
    write(state.with_suffix('.receipt.json'), {'attempted_at': 5000,
          'budget_history': {'distinct_samples': [sample]}})
    cost_sampling.attempted(population, {'agent': 'worker', 'harness': 'codex',
                            'session': 'session', 'path': '/synthetic/transcript'}, 5000)
    rotation = json.loads((population / 'cost-active-rotation.json').read_text())
    assert len(rotation['samples']) == 1 and rotation['samples'][0]['attempted_at'] == 5000
    archived = state.parent / 'predecessor' / 'rotation.json'
    assert len(json.loads(archived.read_text())['samples']) == 20
