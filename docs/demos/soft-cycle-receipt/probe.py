#!/usr/bin/env python3
"""Actual base/candidate verifier, disposable hook/pane fixture; no live cycle."""
import ast
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from shantytown import cli, cycle, soft_cycle
from shantytown.protocols import Agent

BASE = subprocess.check_output(['git', '-C', str(ROOT), 'merge-base', 'HEAD', 'origin/main'], text=True).strip()
text = subprocess.check_output(['git', '-C', str(ROOT), 'show', BASE + ':shantytown/cli.py'], text=True)
node = next(n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == '_cycle_soft')
namespace = dict(cli.__dict__)
exec(compile(ast.Module(body=[node], type_ignores=[]), '<base verifier>', 'exec'), namespace)
base_verify = namespace['_cycle_soft']
# Copy, never modify shared module singletons or real executable objects.
harness = types.SimpleNamespace(clear_command_for=lambda *a: '/clear', bypass_intact=lambda *a: True)
triage = types.SimpleNamespace(strip_attrs=lambda s: s, context_tokens_k=lambda s: None, mid_flight=lambda s: False)
for env in (namespace,):
    env.update(harness_mod=harness, triage_mod=triage, _CLEAR_SETTLE_S=.02,
               _CLEAR_POLL_S=.001, _capture_history_before_kill=lambda *a: None)
# Execute the exact candidate function with fixture-only dependencies too.
node = next(n for n in ast.parse((ROOT / 'shantytown/cli.py').read_text()).body if isinstance(n, ast.FunctionDef) and n.name == '_cycle_soft')
newspace = dict(namespace)
exec(compile(ast.Module(body=[node], type_ignores=[]), '<candidate verifier>', 'exec'), newspace)


def measure(verify):
    with tempfile.TemporaryDirectory(prefix='soft-cycle-demo-') as temp:
        root = Path(temp)
        def observe(session, transcript):
            path = root / 'context_budget/worker.json'
            path.parent.mkdir(exist_ok=True)
            path.write_text(json.dumps(dict(payload=dict(session_id=session, transcript_path=transcript), at=cli.time.time())))
        observe('old', 'old.jsonl')
        cycle.Requests(root).request('worker', 'private fixture checkpoint')
        class Pane:
            sends = 0
            screen = 'old text without a token footer'
            def send(self, *a):
                self.sends += 1
                self.screen = 'ready-looking Stop continuation'
            def capture(self, *a): return self.screen
        pane = Pane()
        args, card = types.SimpleNamespace(root=root), Agent(name='worker', dangerous=False)
        runtime = types.SimpleNamespace(shows_ready_ui=lambda _: True)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            first = verify(args, card, 'worker', 'private-pane', pane, runtime)
            if first: cycle.Requests(root).clear('worker')
            retained = bool(cycle.Requests(root).pending())
            later = None
            if not first:
                verify(args, card, 'worker', 'private-pane', pane, runtime)
                assert pane.sends == 1
                observe('new', 'new.jsonl')
                later = verify(args, card, 'worker', 'private-pane', pane, runtime)
        return dict(initial_verified=first, request_retained=retained, clear_sends=pane.sends, late_session_verified=later)


old, new = measure(base_verify), measure(newspace['_cycle_soft'])
print(json.dumps(dict(target='isolated actual verifier, no live pane', base=BASE, before=old, after=new), sort_keys=True))
assert old['initial_verified'] and not old['request_retained']
assert not new['initial_verified'] and new['request_retained']
assert new['clear_sends'] == 1 and new['late_session_verified']
print('PASS: Stop continuation withheld; request retained; no duplicate clear; actual new session accepted')
