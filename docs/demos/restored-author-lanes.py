"""Read-only library demo of base/current author and review admission.

Run from the repository root with Python >= 3.11. No dispatch or HTTP is used.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

BASE = '7420239f03924fa166531e3cc5a8ca1232345041'
PROBE = '''
from types import SimpleNamespace as NS
from shantytown import governor as gov, work_class
from shantytown.protocols import Agent
import os

base = os.environ['DEMO_REVISION'] == 'base'
print(os.environ['DEMO_REVISION'] + ':')
for title, labels in [('ordinary', []), ('routine', ['work:docs']),
    ('design', ['work:design']),
    ('important code', ['work:important-quipu-code']),
    ('legacy authorized', ['work:design', 'work:claude-authorized']),
    ('review with authorization', ['work:review', 'work:design', 'work:claude-authorized'])]:
    results = []
    for lane in ['claude', 'codex']:
        card = Agent('fixture-author', harness=lane)
        verdict = work_class.for_card(gov.Verdict(reading=gov.Reading(source='none')),
                                      gov.Policy(admit_class=True), card)
        item = NS(id='fixture', priority=1, labels=labels)
        admitted = not verdict.admits(item, card.name)
        expected = lane == 'codex' or ('work:review' not in labels and (not base or title == 'legacy authorized'))
        assert admitted == expected, (title, lane, admitted)
        assert verdict.frozen is False
        from dataclasses import replace
        assert replace(verdict, frozen=True).admits(item, card.name)
        results.append(lane + '=' + ('ADMIT' if admitted else 'REFUSE'))
    print('  ' + title + ': ' + ', '.join(results))
print('  frozen control: REFUSE for both harnesses; no target harness changes')
'''

env = {k: v for k, v in os.environ.items() if not k.startswith(
    ('SHANTY_', 'ST_', 'QUIPU_', 'CLAUDE', 'CODEX_'))}
print('Isolated library predicates, admit_class=true; no assignments or live writes.', flush=True)
with tempfile.TemporaryDirectory() as root:
    archive = subprocess.check_output(['git', 'archive', BASE, 'shantytown'])
    subprocess.run(['tar', '-x', '-C', root], input=archive, check=True)
    for name, source in [('base', root), ('candidate', str(Path.cwd()))]:
        print('Source:', BASE if name == 'base' else 'current checkout', flush=True)
        subprocess.run([sys.executable, '-c', PROBE], cwd=source,
                       env={**env, 'PYTHONPATH': source, 'DEMO_REVISION': name}, check=True)
