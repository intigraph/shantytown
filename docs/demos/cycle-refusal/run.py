"""Demonstrate only private receipt files; never invoke a lifecycle command."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Barrier
from unittest.mock import patch
import os

from shantytown import cycle

BASE = 'bf6869199bdeae416c88284c3e9106abd65a4402'
old_source = subprocess.check_output(['git', 'show', BASE + ':shantytown/cycle.py'])
old_files = subprocess.check_output(['git', 'show', BASE + ':shantytown/files.py'])
from shantytown import files
assert old_files == Path(files.__file__).read_bytes(), 'base helper changed; use the recorded revision'
spec = importlib.util.spec_from_loader('shantytown._cycle_before', loader=None)
old = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = old
exec(compile(old_source, 'base-cycle.py', 'exec'), old.__dict__)


def collision(request_type):
    with tempfile.TemporaryDirectory(prefix='cycle-receipt-demo-') as directory:
        requests = request_type(Path(directory))
        barrier, replace = Barrier(2), os.replace
        def together(source, target):
            barrier.wait(timeout=5)
            return replace(source, target)
        errors = []
        with patch('os.replace', side_effect=together):
            with ThreadPoolExecutor(max_workers=2) as pool:
                jobs = [pool.submit(requests._save, {name: {'checkpoint': name}})
                        for name in ('first', 'second')]
                for job in jobs:
                    try:
                        job.result(timeout=10)
                    except FileNotFoundError as error:
                        errors.append(type(error).__name__)
        assert isinstance(json.loads(requests.path.read_text()), dict)
        return errors


print('BEFORE', BASE, 'same input: two writes ready before either rename')
before = collision(old.Requests)
print('write errors:', before)
assert before == ['FileNotFoundError']
print('AFTER cycle.py SHA256', hashlib.sha256(Path(cycle.__file__).read_bytes()).hexdigest())
after = collision(cycle.Requests)
print('write errors:', after)
assert after == []
with tempfile.TemporaryDirectory(prefix='cycle-receipt-control-') as directory:
    requests = cycle.Requests(Path(directory))
    requests.request('worker', 'private checkpoint')
    assert requests.mark_refused('worker', 'unfinished work', [cycle.TreeRisk('/fixture/unfinished', dirty=True)])
    assert requests.pending()['worker']['refused']['paths'] == ['/fixture/unfinished']
print('positive control: request and named refusal retained')
print('Private file fixtures only; no cycle, pane or running service changed.')
