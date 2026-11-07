"""Isolated library probe; requires the repository's pytest test dependency."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import sys

BASE = '44b46a28ed6a49cab4a8406b8b372625e2c60862'
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from shantytown import refill_reconcile as candidate


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


with tempfile.TemporaryDirectory() as directory:
    directory = Path(directory)
    source = subprocess.check_output(['git', '-C', str(ROOT), 'show',
                                      BASE + ':shantytown/refill_reconcile.py'])
    original = directory / 'base.py'
    original.write_bytes(source)
    base = load('shantytown._demo_base', original)
    fixture = load('_demo_fixture', ROOT / 'tests/test_refill_reconcile.py')
    root, request, _, _, history = fixture.packet.__wrapped__(directory)
    metadata, event = history.read_bytes().splitlines(keepends=True)
    unrelated = json.dumps(dict(type='tool_result', output='x' * 2_272_787)).encode() + b'\n'
    history.write_bytes(metadata + unrelated + event)
    request['line'] = 3
    before = fixture.snapshot(root)
    print('Isolated fixture: >2 MiB unrelated event before exact native receipt at line 3')
    for label, module in [('base ' + BASE, base), ('candidate source', candidate)]:
        try:
            result = module.reconcile(root, request, now=1100)
            print(label + ': ' + result['state'])
            assert module is candidate
        except ValueError as error:
            print(label + ': REFUSED: ' + str(error))
            assert module is base
    assert fixture.snapshot(root) == before
    request['event_sha256'] = '0' * 64
    try:
        candidate.reconcile(root, request, now=1100)
    except ValueError as error:
        print('Wrong-hash control: REFUSED: ' + str(error))
    else:
        raise AssertionError('wrong hash admitted')
    assert fixture.snapshot(root) == before
    print('Read-only probe: all deployment fixture bytes unchanged')
