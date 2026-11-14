"""Offline comparison of dependency priority decisions; no tracker/network writes."""
import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from shantytown.gate_backstop import validate_gate

base = types.ModuleType('shantytown._base_gate')
base.__package__ = 'shantytown'
source = subprocess.check_output(['git', 'show', 'f909de3e3ba445946545dd673f94edea1de2d0fd:shantytown/gate_backstop.py'], text=True)
exec(compile(source, '<committed-base>', 'exec'), base.__dict__)
parent = SimpleNamespace(id='work', priority=0, notes='')
for phase in ['ordinary', 'planned', 'inflight']:
    context = None if phase == 'ordinary' else {'deploy_admission': {
        'schema': 'aegis.deploy-admission/v1', 'phase': phase}}
    target = SimpleNamespace(id='operation', priority=2, agent_context=context)
    before = base.validate_gate(parent, target, 'Exclusive operation must finish')
    after = validate_gate(parent, target, 'Exclusive operation must finish')
    print(f'{phase}: dependency priority before={before}, after={after}')
    assert after == (0 if phase == 'ordinary' else 2)
print('PASS: ordinary inheritance retained; admitted operation priority preserved')
