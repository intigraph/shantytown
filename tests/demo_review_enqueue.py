"""Offline custody demonstration. Run with test extras installed.

    PYTHONPATH=.:tests python3 tests/demo_review_enqueue.py

Uses the signed RDF fixture from the tests, never a live key or service.
"""
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from test_job_review import job
from test_gate_verdict import HEAD, NOW
from shantytown import job_review
from shantytown.actor_identity import IdentityError


def main():
    try:
        from shantytown.review_enqueue import Store
    except ModuleNotFoundError:
        print('before: no review enqueue custody contract is available')
        return
    with TemporaryDirectory() as temporary, pytest.MonkeyPatch.context() as patch:
        path = Path(temporary)
        fstat = os.fstat
        # Only fixture outer ancestry is modelled immutable; the newly created
        # directory, files, signatures and fsyncs use the production functions.
        outer = {(p.stat().st_dev, p.stat().st_ino) for p in (path, *path.parents)
                 if p.stat().st_mode & 0o022}
        def ancestry(fd):
            meta = fstat(fd)
            if (meta.st_dev, meta.st_ino) in outer:
                fields = list(meta)
                fields[0] &= ~0o022
                return os.stat_result(fields)
            return meta
        patch.setattr(os, 'fstat', ancestry)
        spec, q, _, _ = job.__wrapped__(path, patch)
        proof = job_review.write(spec, 'approve', HEAD, 'https://example.invalid/review', quipu=q, now=NOW)
        spec['uid'] += 10001
        root = path / 'controller'
        root.mkdir(mode=0o700)
        (root / 'ephemeral').mkdir(mode=0o700)
        (root / 'ephemeral' / 'review-enqueue').mkdir(mode=0o700)
        message = {'verdict': 'approve', 'review': proof}
        with Store(root) as store:
            row = store.retain('https://github.com', spec, message, quipu=q)
            print('verified APPROVE ->', row['state'])
            assert store.retain('https://github.com', spec, message, quipu=q) == row
            print('duplicate delivery -> same intent')
            row = store.begin(row['id'])
            print('before any remote mutation ->', row['state'])
        print('simulated controller exit; job teardown is independent')
        with Store(root) as store:
            print('reopened custody ->', store.read(row['id'])['state'])
            try:
                store.begin(row['id'])
            except IdentityError:
                print('second attempt -> REFUSED; remote reconciliation required')
            else:
                raise AssertionError('duplicate attempt was allowed')
        print('remote mutations: 0; merge jobs spawned: 0 (offline fixture only)')


if __name__ == '__main__':
    main()
