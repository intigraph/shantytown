"""Offline before/candidate demo; no SSH, launchctl, or tracker requests.

Run from the repository root: python docs/demos/launchd-routing/probe.py BASE
"""
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import types
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


def module(name, source):
    value = types.ModuleType('shantytown.' + name)
    value.__package__ = 'shantytown'
    sys.modules[value.__name__] = value
    exec(compile(source, name, 'exec'), value.__dict__)
    return value


def probe(label, source):
    supervisor = module(label + '_supervisor', source('supervisor'))
    governor = module(label + '_governor', source('fleet_governor'))
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / 'root'
        root.mkdir()
        (root / 'shantytown.toml').write_text('[env]\nSHANTY_BACKEND="seeds"\n')
        with patch.dict(os.environ, {'SHANTY_BACKEND': 'files'}):
            supervisor.install_launchd('/example/bin/st', root,
                                       agents_dir=Path(directory) / 'agents',
                                       path_env='/example/bin:/usr/bin')
        env = plistlib.loads((Path(directory) / 'agents' /
                              'shantytown.st-tend.plist').read_bytes())['EnvironmentVariables']
        result = subprocess.CompletedProcess([], 255, '',
                                            'previous private line\nssh: connect: No route to host\n')
        with patch.object(governor.subprocess, 'run', return_value=result):
            state, error = governor.read_peer(types.SimpleNamespace(
                root='/example/root', ssh='example-peer', name='peer'))
        return {'backend': env.get('SHANTY_BACKEND'),
                'path_preserved': env.get('PATH') == '/example/bin:/usr/bin',
                'root_preserved': env.get('SHANTY_ROOT') == str(root.resolve()),
                'peer_unavailable': state is None,
                'reason': str(error), 'production_calls': 0}


if __name__ == '__main__':
    base = sys.argv[1]
    before = probe('before', lambda name: subprocess.check_output(
        ['git', 'show', f'{base}:shantytown/{name}.py'], text=True))
    after = probe('candidate', lambda name: Path(f'shantytown/{name}.py').read_text())
    assert before['backend'] is None and 'No route to host' not in before['reason']
    assert after['backend'] == 'seeds' and 'No route to host' in after['reason']
    assert all(value[key] for value in (before, after)
               for key in ('path_preserved', 'root_preserved', 'peer_unavailable'))
    print(json.dumps({'base': base, 'before': before, 'candidate': after}, indent=2))
