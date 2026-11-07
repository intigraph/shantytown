"""Compare retained refresh functions with isolated injected operations only."""
import ast
from pathlib import Path
import subprocess
import sys

from shantytown import cli

ref = sys.argv[1]
source = subprocess.check_output(['git', 'show', f'{ref}:shantytown/cli.py'], text=True)
revision = subprocess.check_output(['git', 'rev-parse', ref], text=True).strip()
node = next(node for node in ast.parse(source).body
            if isinstance(node, ast.FunctionDef) and node.name == '_refresh_agent_worktrees')
module = ast.Module(body=[node], type_ignores=[])
exec(compile(module, 'retained-refresh-function.py', 'exec'), cli.__dict__)
print('Source revision:', revision, flush=True)
exec(compile(Path('docs/probes/tend-refresh-budget/probe.py').read_text(), 'probe.py', 'exec'))
