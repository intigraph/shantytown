"""Source-only library demo; private fixtures, no service or tracker calls."""
import hashlib
import json
import subprocess
import sys
import types
from pathlib import Path

from shantytown import deferrals, resume_events
from tests.test_resume_events import BINDING, NOW, evidence, row

base = 'be8eba5a4c8b9a0509b2b9169165e5711efcd6fb'
module = types.ModuleType('_sw5_base')
sys.modules[module.__name__] = module
raw = subprocess.check_output(['git', 'show', base + ':shantytown/deferrals.py'])
exec(compile(raw, '<base deferrals>', 'exec'), module.__dict__)
print('Target: source library, synthetic registered producer; no runtime activation')
print('Base:', base)
for name in ('deferrals.py', 'resume_events.py'):
    print('Candidate source SHA256:', name,
          hashlib.sha256((Path('shantytown') / name).read_bytes()).hexdigest())
before = module.evaluate([row()], NOW)[0]
print(json.dumps({'before': 'UNTESTABLE', 'met': before.met,
                  'reason': before.untestable}))
for label, change in [('natural pair', {}), ('manual recycle', {'natural': False}),
                      ('wrong generation', {'generation': 'different'})]:
    data = evidence()
    data['events'][1].update(change)
    answer = resume_events.decide(BINDING, data, NOW)
    print(json.dumps({'input': label, 'after': answer.state, 'reason': answer.reason}))
print('Production binding accepted:',
      resume_events.REGISTRY['protected-recycle-v1'].accepted)
assert not before.met and not resume_events.REGISTRY['protected-recycle-v1'].accepted
assert deferrals.parse_condition(row()['notes']).testable()
