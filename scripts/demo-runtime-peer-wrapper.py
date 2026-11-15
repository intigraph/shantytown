#!/usr/bin/env python3
"""Exercise the actual runtime wrapper with private admission and version fixtures."""
import ast
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from shantytown import cli
from test_runtime_roll import test_actual_tend_wrapper_collects_peers_under_admission as probe

BASE = '8f792ab7fadc9185b0737051b97b4c15a8edfc41'
original = cli._runtime_roll_sweep
source = subprocess.check_output(['git', '-C', str(ROOT), 'show', BASE + ':shantytown/cli.py'], text=True)
function = next(node for node in ast.parse(source).body
                if isinstance(node, ast.FunctionDef) and node.name == '_runtime_roll_sweep')
namespace = vars(cli).copy()
exec(compile(ast.Module(body=[function], type_ignores=[]), 'base-wrapper', 'exec'), namespace)
try:
    for label, wrapper in [('BASE ' + BASE, namespace['_runtime_roll_sweep']), ('CANDIDATE', original)]:
        print(label, flush=True)
        cli._runtime_roll_sweep = wrapper
        for case in ['current', 'unknown', 'awaiting-version', 'owner-unreachable']:
            with tempfile.TemporaryDirectory(prefix='runtime-wrapper-demo-') as directory:
                with pytest.MonkeyPatch.context() as patch:
                    try:
                        probe(Path(directory), patch, case)
                    except NameError as error:
                        assert label.startswith('BASE ') and error.name == 'fleet_mod'
                        print(case + ': actual wrapper raises NameError(fleet_mod)', flush=True)
                    else:
                        assert label == 'CANDIDATE' or case == 'owner-unreachable'
                        print(case + ': ' + ('one no-in-place request admitted; checkpoint retained'
                              if case == 'current' else 'no request or checkpoint; admission withheld'), flush=True)
finally:
    cli._runtime_roll_sweep = original
print('Private source fixture only; no peer contact, credentials, pane input or process replacement.', flush=True)
