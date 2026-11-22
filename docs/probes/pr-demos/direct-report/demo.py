"""Offline prompt and native command-policy probe; no job is launched."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from shantytown import ephemeral as candidate

BASE = '6fc8c2fff7581d87e1a7dda2e6d946b295693ac0'
source = subprocess.run(['git', 'show', BASE + ':shantytown/ephemeral.py'],
                        cwd=ROOT, check=True, capture_output=True, text=True).stdout
baseline = types.ModuleType('shantytown.report_demo_baseline')
baseline.__package__ = 'shantytown'
sys.modules[baseline.__name__] = baseline
exec(compile(source, 'baseline-ephemeral.py', 'exec'), baseline.__dict__)
rec = dict(name='eph-task-abc123', job='task', harness='codex', item='fixture-1',
           repo=None, pr=None, administrator='controller', deadline=1_800_000_000,
           max_turns=2)

print('OFFLINE: rendered source prompts and native policy check; no report or launch.')
for label, module in [('BEFORE', baseline), ('AFTER', candidate)]:
    text = module.prompt(rec)
    line = next(s.strip() for s in text.splitlines() if s.strip().startswith('st agent spawn --report'))
    print(label + ': ' + line)

with tempfile.TemporaryDirectory() as folder:
    rules = Path(folder) / 'report.rules'
    rules.write_text(candidate.codex_job_rules(rec, unattended=False))
    commands = [
        ('DIRECT', ['st', 'agent', 'spawn', '--report', '--verdict', 'done',
                    '--summary', 'DELIVERY-REPORT; harness Codex']),
        ('WRAPPED', ['bash', '-lc', 'st agent spawn --report --verdict done --summary-file - <<EOF\nDELIVERY-REPORT\nEOF']),
        ('CONTROL', ['git', 'push']),
    ]
    for label, command in commands:
        result = subprocess.run(['codex', 'execpolicy', 'check', '--rules', str(rules), '--', *command],
                                check=True, capture_output=True, text=True)
        value = json.loads(result.stdout)
        print(label + ': decision=' + value.get('decision', 'NO MATCH'))
        assert value.get('decision') == {'DIRECT': 'allow', 'WRAPPED': None, 'CONTROL': 'forbidden'}[label]
print('LIMIT: policy matching is not installed live start-to-report acceptance.')
