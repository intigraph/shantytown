"""Isolated stats-to-header demonstration; no network or real credentials.

Run from the repository root: python3 docs/demos/hook-session.py
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import types

from shantytown import owned_work_graph, quipu_auth
from shantytown.quipu import request_headers


BASE = '7510e04d678235a4b3b56bdf7faa907cf49feb1c'
for key in tuple(os.environ):
    if key.startswith(('QUIPU_', 'SHANTY_', 'CODEX_', 'CLAUDE_')) or key == 'CLAUDECODE':
        os.environ.pop(key)
os.environ.update(CLAUDECODE='1', SHANTY_AGENT='fixture-agent', SHANTY_MODEL='fixture-model')
quipu_auth.token = lambda: 'fixture-only'
quipu_auth.status = lambda _: 'ready'
seen = []
owned_work_graph.publish = lambda *a, **kw: seen.append(request_headers().get('X-Quipu-Session'))
payload = {'session_id': 'native-fixture-session', 'hook_event_name': 'PreToolUse'}
print('Target: isolated library hook; publisher intercepted, HTTP disabled.')
print('Input:', json.dumps(payload), '; environment session: absent')
for label, source in [
    ('base ' + BASE, subprocess.check_output(['git', 'show', BASE + ':shantytown/stats.py']).decode()),
    ('candidate stats.py', Path('shantytown/stats.py').read_text()),
]:
    module = types.ModuleType('shantytown.demo_stats')
    module.__package__ = 'shantytown'
    module.__file__ = str(Path('shantytown/stats.py').resolve())
    exec(compile(source, module.__file__, 'exec'), module.__dict__)
    with tempfile.TemporaryDirectory() as root:
        module.capture(Path(root), payload)
    print(label + ': publication session = ' + repr(seen[-1]))
    print('  outside publication session =', repr(request_headers().get('X-Quipu-Session')))
assert seen == [None, 'native-fixture-session'], seen
assert 'X-Quipu-Session' not in request_headers()
