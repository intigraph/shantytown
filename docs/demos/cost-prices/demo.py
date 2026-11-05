#!/usr/bin/env python3
"""Source-level fixture only; no tracker, metrics gateway or graph calls."""
import importlib.util
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
ROOT = Path(__file__).resolve().parents[3]
BASE = 'bccb036cd65183cc16f79a2c56fe24419565afbe'
sys.path.insert(0, str(ROOT))
from shantytown import cost
result = {'groups': [], 'costs': {'price_table_sha256': 'fixture-sha', 'groups': [
    {'rig':'example','bead':'task-a','agent':'worker','harness':'claude',
     'model':'example-model','basis':'declared','usd':None,'known_usd':'0.5',
     'tokens':100,'priced_tokens':50,'unknown_reasons':{'unknown token category':1}}]}}
with TemporaryDirectory() as directory:
    path = Path(directory)/'cost_base.py'
    path.write_bytes(subprocess.check_output(['git','show',BASE+':shantytown/cost.py'], cwd=ROOT))
    spec = importlib.util.spec_from_file_location('shantytown.cost_base', path)
    old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)
    print('BASE '+BASE)
    before = old.metrics(result)
    print('Currency samples:', [line for line in before.splitlines() if line.startswith('st_bead_api_equivalent')])
    print('CANDIDATE display source')
    print(cost.price_description(result, 'task-a'))
    after = cost.metrics(result)
    for line in after.splitlines():
        if line.startswith(('st_bead_api_equivalent','st_bead_priced_token_share')):
            print(line)
    assert 'st_bead_api_equivalent_usd{' not in after
    assert 'st_bead_api_equivalent_known_usd{' in after
    assert cost.receipt(result,'task-a') is None
print('PASS: partial subtotal has a separate metric; complete dollars and receipt remain absent')
