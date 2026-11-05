#!/usr/bin/env python3
"""Compare actual library behavior in disposable fixtures; no live pane or inbox."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from shantytown import delivery
import test_delivery_custody as fixtures

BASE = 'e126d6d61415d3f8cf386caf6ff69ba37ec28d4b'


def probe(module, label):
    fixtures.delivery = module
    for case in ('old-session', 'drained', 'busy', 'watch'):
        with tempfile.TemporaryDirectory() as folder, pytest.MonkeyPatch.context() as patch:
            root = Path(folder)
            f = fixtures.fixtures(root, patch, state=None)
            count = 4 if case == 'old-session' else 1
            for index in range(count):
                with module.Custody(root, 'worker') as custody:
                    custody.begin(f'fixture notice {index}', 17.0)
                    if case == 'watch':
                        custody.record.update(pointer='fixture-read-pointer', pointer_state='recorded')
                    custody.finish('queued')
            # Frame/session/inbox are synthetic; supervise and custody files are real.
            if case in ('old-session', 'watch'):
                patch.setattr(f[0], 'session_created', lambda _: 99.0)
            watch = root / 'delivery' / ('watch-' + hashlib.sha256(b'worker').hexdigest() + '.json')
            if case == 'watch':
                watch.write_text(json.dumps({'id': watch.stem, 'since': 1, 'alerted': True}))
            screen = fixtures.QUEUED if case == 'busy' else fixtures.READY
            fixtures.observe(root, f, screen, 1000)
            states = sorted({row['state'] for row in fixtures.records(root)})
            unread = len(f[-1].unread('worker'))
            print(f'{label} {case}: states={states}, unread={unread}, watch_exists={watch.exists()}')
            assert fixtures.keys(f[1]) == []
            expected = {'old-session': (['orphaned'], 1), 'drained': (['dequeued'], 1),
                        'busy': (['queued'], 1), 'watch': (['orphaned'], 0)}
            if label == 'after':
                assert (states, unread) == expected[case]
                if case == 'watch':
                    assert not watch.exists()
                else:
                    assert watch.exists()
            else:
                assert states == ['queued']
                if case == 'watch':
                    assert watch.exists()


with tempfile.TemporaryDirectory() as folder:
    path = Path(folder) / 'baseline.py'
    path.write_bytes(subprocess.check_output(['git', 'show', BASE + ':shantytown/delivery.py'], cwd=ROOT))
    spec = importlib.util.spec_from_file_location('shantytown.delivery_baseline', path)
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)
    print('Disposable source-library fixtures; session and screen observations mocked. No live delivery.')
    print('before source:', BASE)
    print('after delivery.py SHA256:', hashlib.sha256((ROOT / 'shantytown/delivery.py').read_bytes()).hexdigest())
    probe(baseline, 'before')
    probe(delivery, 'after')
    print('Control: busy queue retained; zero keys sent in every case. Runtime acceptance remains open.')
