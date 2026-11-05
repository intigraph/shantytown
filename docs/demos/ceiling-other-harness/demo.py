"""Offline library comparison; no dispatch, tracker, credentials or network."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import types

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from shantytown import ceiling_transfer as candidate

BASE = '8ee0f7eaa1bd453838e2a4df69a5eea83673449e'
source = subprocess.check_output(['git', '-C', str(ROOT), 'show',
                                  BASE + ':shantytown/ceiling_transfer.py'], text=True)
baseline = types.ModuleType('ceiling_demo_baseline')
sys.modules[baseline.__name__] = baseline
exec(compile(source, '<pinned-base>', 'exec'), baseline.__dict__)

print('Target: isolated library fixtures; no live transfers')
print('Base:', BASE)
print('Input: Claude source at usage ceiling; live Claude and Codex receivers, both count=0')
for label, module in [('before', baseline), ('after', candidate)]:
    fields = {'harness': 'claude'} if 'harness' in module.Holder.__dataclass_fields__ else {}
    holder = module.Holder('source', 'fixture-work', 'usage limit', 'synthetic evidence', **fields)
    receivers = [module.Candidate('same-harness', 'claude', 0),
                 module.Candidate('other-harness', 'codex', 0)]
    plan = module.plan([holder], receivers)
    actual = [move.to for move in plan.moves]
    print(label + ':', actual)
    assert actual == (['same-harness'] if label == 'before' else ['other-harness'])

rows = [dict(id=f'deferred-{i}', title='Work', assignee='receiver', status='deferred')
        for i in range(52)]
rows += [dict(id='held', title='Work', assignee='receiver', status='in_progress',
              labels=['blocked:external']),
         dict(id='active', title='Work', assignee='receiver', status='in_progress')]
count = candidate.active_plate_count(rows, 'receiver')
print('Candidate active count: 52 deferred + 1 held + 1 active ->', count)
assert count == 1
holder = candidate.Holder('source', 'fixture-work', 'usage limit', 'synthetic evidence',
                          harness='claude')
control = candidate.plan([holder], [candidate.Candidate('full', 'codex', candidate.PLATE_CAP)])
print('Full-receiver negative control: moves=', len(control.moves), sep='')
assert not control.moves
