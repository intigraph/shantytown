"""Run the parser-only namespace-shadow regression; launches no cycle."""
from pathlib import Path
import runpy
import subprocess
import tempfile
import sys

from pytest import MonkeyPatch

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))
case = runpy.run_path(str(root / 'tests/test_self_cycle_performs.py'))
run = subprocess.run


def observed(*args, **kwargs):
    result = run(*args, **kwargs)
    if result.returncode:
        print(f'Inherited namespace-shadow cwd: exit={result.returncode}')
        print(next(line for line in result.stderr.splitlines()
                   if line.startswith('ImportError:')))
    else:
        print(f'Waiter spawn cwd: exit={result.returncode}; '
              f'parser exposes --root={"--root" in result.stdout}')
    return result


print('Synthetic editable-install fixture; identical parser probe; no lifecycle action.')
with tempfile.TemporaryDirectory() as directory, MonkeyPatch.context() as patch:
    patch.setattr(subprocess, 'run', observed)
    case['test_waiter_parser_survives_a_namespace_shadow_in_the_callers_cwd'](
        Path(directory), patch)
print('Regression assertions passed.')
