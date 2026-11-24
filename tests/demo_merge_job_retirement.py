"""Offline library probe; no job launch, forge read or merge."""
import subprocess
import sys
import tempfile
import types
from pathlib import Path
from shantytown import config, ephemeral

BASE = 'f3e7f02015f5339bad8b8c87cbb38b8d9c8c372c'
base = types.ModuleType('shantytown.retirement_before')
base.__package__ = 'shantytown'
sys.modules[base.__name__] = base
exec(subprocess.check_output(['git', 'show', BASE + ':shantytown/ephemeral.py'], text=True), base.__dict__)
print('Offline plan probe: before', BASE, 'and candidate source checkout')
for label, module, enabled in [('before', base, True), ('after', ephemeral, True),
                               ('flag-OFF control', ephemeral, False)]:
    with tempfile.TemporaryDirectory() as directory:
        try:
            record = module.plan(module.Request('merge', 'example-1', repo='example/project', pr=1,
                                                head='a' * 40), root=Path(directory),
                                 policy=config.Ephemeral(review_enqueue_enabled=enabled),
                                 actor='controller', administrator='controller', host=None, now=1000,
                                 role_of=lambda _: 'administrator', name='eph-merge-example')
            print(label + ': merge job admitted (' + record['state'] + ')')
            assert label != 'after'
        except module.Refused as error:
            print(label + ': REFUSED: ' + str(error))
            assert label == 'after'
print('No ledger written, launch, forge read or remote mutation.')
