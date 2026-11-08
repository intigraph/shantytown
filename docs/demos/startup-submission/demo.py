"""Synthetic launch boundary: no runtime, pane, tracker or network operations."""
import ast
import contextlib
import io
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from shantytown import cli, job_launch
from shantytown.protocols import Agent

BASE = '6bb4694988539c60fbc1a4060a9ecb75fe9c8bcf'


def launcher(source):
    node = next(n for n in ast.parse(source).body
                if isinstance(n, ast.FunctionDef) and n.name == '_launch_admitted')
    scope = dict(vars(cli))
    scope.update(
        _administrator_launch=lambda *a: True,
        _window_launch_gate=lambda *a: None,
        _account_launch_refusal=lambda *a, **kw: '',
        _session_for=lambda *a: 'fixture-session',
        _launched_now=lambda *a: None,
        _record_launch_unretirement=lambda *a: True,
        _observe_live=lambda *a: True,
        _verify_live_hooks=lambda *a: cli.OK,
    )
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<launch-fixture>', 'exec'), scope)
    return scope


print('Synthetic fixture: live process + verified hooks; startup delivery varies.')
print('No crew launch, keystrokes, tracker mutation or network.')
base = subprocess.check_output(['git', 'show', BASE + ':shantytown/cli.py'], cwd=ROOT)
for label, source in [('before ' + BASE[:8], base),
                      ('candidate', (ROOT / 'shantytown/cli.py').read_bytes())]:
    scope = launcher(source)
    for delivered in (False, True):
        scope['_deliver_startup_inbox'] = lambda *a: delivered
        with TemporaryDirectory() as root, contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(cli.quiet_time_mod, 'read',
                                             return_value=SimpleNamespace(held=False)))
            stack.enter_context(patch.object(job_launch, 'for_card', return_value=('fixture',)))
            stack.enter_context(patch.object(cli.harness_mod, 'require_role_harness'))
            runtime = SimpleNamespace(compose=lambda *a: 'fixture', start=lambda *a: None,
                                      settings_path=lambda *a: None)
            panes = SimpleNamespace(new_session=lambda *a, **kw: None)
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                result = scope['_launch_admitted'](SimpleNamespace(root=Path(root)),
                    Agent('fixture', role='administrator', harness='claude'), panes, runtime)
        print(f'{label}: startup_delivered={delivered} -> exit {result}')
        assert result == (2 if label == 'candidate' and not delivered else 0)
print('PASS: failed startup is unverified; successful control remains exit 0.')
