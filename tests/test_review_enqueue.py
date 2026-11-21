"""Offline signed reviews and private custody; no forge or launcher calls."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
import stat
import threading

import pytest

from test_job_review import job  # noqa: F401 -- signed RDF/key fixture
from test_gate_verdict import HEAD, NOW
from shantytown import job_review, review_enqueue as requeue
from shantytown.actor_identity import IdentityError


@pytest.fixture
def custody(tmp_path, monkeypatch, job):
    fstat = os.fstat
    outer = {(p.stat().st_dev, p.stat().st_ino) for p in tmp_path.parents
             if p.stat().st_mode & 0o022}
    def ancestry(fd):
        meta = fstat(fd)
        if (meta.st_dev, meta.st_ino) in outer:
            fields = list(meta)
            fields[0] &= ~0o022
            return os.stat_result(fields)
        return meta
    monkeypatch.setattr(requeue.os, 'fstat', ancestry)
    root = tmp_path / 'controller'
    directory = root / 'ephemeral' / 'review-enqueue'
    root.mkdir(mode=0o700)
    (root / 'ephemeral').mkdir(mode=0o700)
    directory.mkdir(mode=0o700)
    spec, q, _, _ = job
    proof = job_review.write(spec, 'approve', HEAD, 'https://example.invalid/review', quipu=q, now=NOW)
    spec['uid'] += 10001  # The controller is independent of the modelled job UID.
    return root, directory, spec, q, {'verdict': 'approve', 'review': proof}


def retain(store, fixture):
    _, _, spec, q, message = fixture
    return store.retain('https://github.com', spec, message, quipu=q)


def test_verified_approval_survives_teardown_and_reopen_without_rearming(custody):
    root, directory, spec, _, _ = custody
    with requeue.Store(root) as store:
        first = retain(store, custody)
        assert first['state'] == 'pending'
        assert retain(store, custody) == first
    # No job home or mailbox is needed to read durable controller custody.
    spec['home'] = '/nonexistent/reaped-job'
    with requeue.Store(root) as store:
        assert store.read(first['id']) == first
        attempted = store.begin(first['id'])
    assert stat.S_IMODE((directory / (first['id'] + '.json')).stat().st_mode) == 0o600
    with requeue.Store(root) as store:
        assert store.read(first['id']) == attempted
        with pytest.raises(IdentityError, match='consumed'):
            store.begin(first['id'])


@pytest.mark.parametrize('fault', ['unsigned', 'head', 'changes', 'same-uid', 'untrusted',
                                  'author', 'authority', 'revoked', 'authorship-changed'])
def test_invalid_review_never_creates_intent(custody, monkeypatch, fault):
    root, directory, spec, q, message = custody
    authority = 'https://github.com'
    if fault == 'unsigned': message.pop('review')
    elif fault == 'head': message['review']['head'] = 'b' * 40
    elif fault == 'changes': message['verdict'] = 'request-changes'
    elif fault == 'same-uid': spec['uid'] = os.geteuid()
    elif fault == 'untrusted': monkeypatch.setattr(job_review.gv, 'trusted_signers', lambda: {})
    elif fault == 'author': spec['review']['author_agent'] = spec['principal']
    elif fault == 'authority': authority = 'https://github.com/other'
    elif fault == 'revoked': q.registry.clear()
    elif fault == 'authorship-changed':
        job_review.gv.write_authorship(quipu=q, graph=spec['review']['graph'],
                                      node_id=spec['review']['pr_node'], agent='another-author')
    with requeue.Store(root) as store:
        with pytest.raises(IdentityError):
            store.retain(authority, spec, message, quipu=q)
    assert not list(directory.glob('*.json'))


def test_new_head_never_inherits_existing_approval(custody):
    root, directory, spec, _, _ = custody
    with requeue.Store(root) as store:
        first = retain(store, custody)
        spec['review']['head'] = 'b' * 40
        with pytest.raises(IdentityError):
            retain(store, custody)
        assert store.read(first['id']) == first
    assert len(list(directory.glob('*.json'))) == 1


@pytest.mark.parametrize('outcome', ['queued', 'refused', 'unknown'])
def test_terminal_outcomes_do_not_retry_even_after_duplicate_report(custody, outcome):
    root, _, _, _, _ = custody
    with requeue.Store(root) as store:
        first = retain(store, custody)
        attempt = store.begin(first['id'])['attempt']
        terminal = store.finish(first['id'], attempt, outcome, 'native-receipt-1')
        assert retain(store, custody) == terminal
        with pytest.raises(IdentityError):
            store.begin(first['id'])
        with pytest.raises(IdentityError):
            store.finish(first['id'], attempt, 'queued', 'different-receipt')


def test_two_controllers_can_consume_only_one_attempt(custody):
    root, _, _, _, _ = custody
    with requeue.Store(root) as store:
        key = retain(store, custody)['id']
    barrier = threading.Barrier(2)
    def begin():
        with requeue.Store(root) as store:
            barrier.wait(timeout=3)
            try:
                store.begin(key)
                return 'begun'
            except (IdentityError, BlockingIOError):
                return 'refused'
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(begin) for _ in range(2)]
        assert sorted(f.result(timeout=5) for f in futures) == ['begun', 'refused']


@pytest.mark.parametrize('fault', ['symlink', 'hardlink', 'mode', 'wrong-id', 'oversize', 'malformed', 'duplicate'])
def test_unproved_custody_is_never_treated_as_empty(custody, fault):
    root, directory, _, _, _ = custody
    with requeue.Store(root) as store:
        first = retain(store, custody)
    path = directory / (first['id'] + '.json')
    if fault == 'symlink':
        target = directory / 'retained'
        path.rename(target)
        path.symlink_to(target)
    elif fault == 'hardlink': os.link(path, directory / 'retained')
    elif fault == 'mode': path.chmod(0o644)
    elif fault == 'wrong-id': path.write_text(json.dumps(first | {'id': 'b' * 64}))
    elif fault == 'oversize': path.write_bytes(b'x' * (requeue.MAX_BYTES + 1))
    elif fault == 'malformed': path.write_text('{')
    elif fault == 'duplicate': path.write_text(path.read_text()[:-1] + ',"state":"queued"}')
    before = path.read_bytes()
    with requeue.Store(root) as store:
        with pytest.raises((IdentityError, OSError)):
            retain(store, custody)
    assert path.read_bytes() == before


def test_crash_before_replace_leaves_evidence_and_no_new_intent(custody, monkeypatch):
    root, directory, _, _, _ = custody
    with requeue.Store(root) as store:
        def crash(*a, **kw):
            raise OSError('synthetic crash before replacement')
        with monkeypatch.context() as patch:
            patch.setattr(requeue.os, 'replace', crash)
            with pytest.raises(OSError):
                retain(store, custody)
        assert list(directory.glob('.prepared-*'))
        with pytest.raises(IdentityError, match='reconciliation'):
            retain(store, custody)
    assert not list(directory.glob('*.json'))


def test_capacity_failure_retains_previous_intent(custody, monkeypatch):
    root, directory, _, _, _ = custody
    monkeypatch.setattr(requeue, 'MAX_INTENTS', 0)
    with requeue.Store(root) as store:
        with pytest.raises(IdentityError, match='capacity'):
            retain(store, custody)
    assert not list(directory.glob('*.json'))


def test_lost_local_acknowledgement_reads_back_without_recreating_intent(custody, monkeypatch):
    root, directory, _, _, _ = custody
    with requeue.Store(root) as store:
        original = store._write
        def lost(value):
            original(value)
            raise OSError('synthetic lost reply after durable replace')
        with monkeypatch.context() as patch:
            patch.setattr(store, '_write', lost)
            with pytest.raises(OSError):
                retain(store, custody)
        path, = directory.glob('*.json')
        before = path.read_bytes()
        first = retain(store, custody)
        assert first['state'] == 'pending' and path.read_bytes() == before


def test_wrong_attempt_cannot_finish_or_rearm(custody):
    root, _, _, _, _ = custody
    with requeue.Store(root) as store:
        key = retain(store, custody)['id']
        attempt = store.begin(key)
        with pytest.raises(IdentityError):
            store.finish(key, '0' * 64, 'queued', 'unrelated-receipt')
        assert store.read(key) == attempt


@pytest.mark.parametrize('mode', [0o755, 0o770])
def test_nonprivate_directory_refuses_before_custody(custody, mode):
    root, directory, _, _, _ = custody
    directory.chmod(mode)
    with pytest.raises(IdentityError):
        requeue.Store(root)
    assert not list(directory.iterdir())
