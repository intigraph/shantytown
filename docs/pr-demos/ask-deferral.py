#!/usr/bin/env python3
"""Compare the base/current dispatcher with private file trackers and no panes."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))
from shantytown import dispatch
from shantytown.files import FilesRegistry, FilesTracker
from shantytown.tmux import NullPanes

source = subprocess.check_output(['git','show','dbabbe84:shantytown/dispatch.py'], cwd=root, text=True)
before = types.ModuleType('shantytown._ask_demo_before')
before.__package__ = 'shantytown'
before.__file__ = str(root/'shantytown/dispatch.py')
sys.modules[before.__name__] = before
exec(compile(source, before.__file__, 'exec'), before.__dict__)
print('Private ASK deferral control (file trackers; no production calls)')
print('case                 before        candidate')
with tempfile.TemporaryDirectory(prefix='ask-demo-') as directory:
    base = Path(directory)
    for case in ['needs-stiwi','blocked:human','desk','decision-needed','title-prefix','non-ASK']:
        results = []
        for name, module in [('before',before),('candidate',dispatch)]:
            path = base/name/case
            tracker = FilesTracker(path/'items')
            title = 'ASK Stiwi: choose' if case == 'title-prefix' else 'Technical control'
            tracker.update('lab-1', title=title, status='open',
                           labels=[] if case in ('title-prefix','non-ASK') else [case])
            initial = tracker._path('lab-1').read_bytes()
            d = module.Dispatcher(FilesRegistry(path/'crew'), tracker, NullPanes())
            try:
                d.defer('lab-1','external','private control',until='2027-01-01')
                result = 'deferred'
            except module.DeferRefused:
                assert tracker._path('lab-1').read_bytes() == initial
                result = 'REFUSED'
            results.append(result)
        assert results == (['deferred','deferred'] if case == 'non-ASK' else ['deferred','REFUSED'])
        print(f'{case:20} {results[0]:13} {results[1]}')
print('PASS: five ASK cases refuse without writes; ordinary deferral succeeds.')
