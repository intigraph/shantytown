"""Read-only base/candidate class-exemption probe, from the repository root."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace

from shantytown import governor, work_class
from shantytown.protocols import Agent

base = sys.argv[1]
root = Path(__file__).resolve().parents[3]
source = subprocess.check_output(['git', 'show', base + ':shantytown/work_class.py'], cwd=root)
with tempfile.TemporaryDirectory() as name:
    path = Path(name) / 'base.py'
    path.write_bytes(source)
    spec = spec_from_file_location('shantytown._keeper_demo_base', path)
    old = module_from_spec(spec)
    spec.loader.exec_module(old)
    for label, module in [('BASE ' + base, old), ('CANDIDATE', work_class)]:
        print(label)
        for role, configured in [('keeper', True), ('worker', True), ('keeper', False)]:
            card = Agent('fixture', role=role, harness='claude')
            policy = governor.Policy(admit_class=True,
                class_exempt=('fixture',) if configured else ())
            verdict = module.for_card(governor.Verdict(reading=governor.Reading(source='none')),
                                      policy, card)
            item = SimpleNamespace(id='job', priority=2, labels=[])
            print(f'role={role} configured={configured}: '
                  f'class_exempt={module.exempt(card, policy)} '
                  f'unlabeled_admitted={not bool(verdict.admits(item, card.name))}')
