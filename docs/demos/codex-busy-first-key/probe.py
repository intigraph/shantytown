#!/usr/bin/env python3
"""Compare actual sender source with isolated terminal protocol frames.
# arming: agent-invoked; no live pane, model call or delivery record.
"""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from shantytown import tmux as candidate
BASE = '895d653b26ca3a7a89016c6f9786b34d9dcc6c33'
SOURCE = 'da57af49e0eda87a5031c128fdec608cd4725e0f'
spec = importlib.util.spec_from_file_location('protocol_controls', ROOT / 'tests/test_codex_submission.py')
controls = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controls)
before = types.ModuleType('shantytown._demo_before_tmux')
before.__package__ = 'shantytown'
before.__file__ = str(ROOT / 'shantytown/tmux.py')
sys.modules[before.__name__] = before
source = subprocess.check_output(['git', '-C', str(ROOT), 'show', BASE + ':shantytown/tmux.py'], text=True)
exec(compile(source, before.__file__, 'exec'), before.__dict__)
wrapped = 'Working (3h • esc to interrupt)\n' + controls.OWNED.replace('assigned', 'assi\n  gned')


def measure(module, case):
    with pytest.MonkeyPatch.context() as patch:
        patch.delenv('SHANTY_ROOT', raising=False)
        patch.delenv('SHANTY_TMUX_SOCKET', raising=False)
        patch.setattr(controls, 'tmux', module)
        if case == 'busy-word-wrap':
            frames, typed = [controls.BUSY, controls.QUEUED], wrapped
        elif case == 'idle':
            frames, typed = [controls.READY, controls.BUSY], controls.OWNED
        else:
            frames, typed = [controls.OWNED.replace(controls.BODY, 'Unrelated human draft')], None
        panes, calls = controls.transport(patch, frames, typed_frame=typed)
        assert panes.delivery_root is None and panes.socket is None
        # Model the measured protocol: while busy, Enter leaves this body
        # typed; Tab queues it. This fixture grants no live-TUI acceptance.
        last_frame = [frames[0]]
        def capture(*args, **kwargs):
            sends = controls.keys(calls)
            literals = [c for c in sends if '-l' in c]
            submitted = [c[-1] for c in sends if '-l' not in c]
            if not literals:
                screen = frames[0]
            elif case == 'busy-word-wrap':
                screen = controls.QUEUED if submitted and submitted[-1] == 'Tab' else wrapped
            else:
                screen = controls.BUSY if submitted else controls.OWNED
            last_frame[0] = screen
            return screen
        patch.setattr(panes, 'capture', capture)
        try:
            panes.send('private-fixture-pane', controls.BODY)
            outcome = 'observed-submission'
        except module.PaneSubmissionUnverified as error:
            outcome = 'unverified-queued' if 'queued input' in str(error) else 'unverified'
        sends = controls.keys(calls)
        return dict(key=[c[-1] for c in sends if '-l' not in c],
                    literal_writes=len([c for c in sends if '-l' in c]), outcome=outcome,
                    composer_typed=controls.triage.input_state(last_frame[0]) == controls.triage.INPUT_QUEUED)


print(json.dumps(dict(target='isolated source/protocol fixture', base=BASE, source=SOURCE)), flush=True)
for case in ['busy-word-wrap', 'idle', 'foreign-draft']:
    old, new = measure(before, case), measure(candidate, case)
    print(json.dumps(dict(case=case, before=old, after=new)), flush=True)
    if case == 'busy-word-wrap':
        assert old['key'] == ['Enter'] and new['key'] == ['Tab']
        assert old['literal_writes'] == new['literal_writes'] == 1
        assert old['outcome'] == 'unverified' and old['composer_typed']
        assert new['outcome'] == 'unverified-queued' and not new['composer_typed']
        assert not candidate._codex_owned_input(wrapped, controls.BODY)
    elif case == 'idle':
        assert old == new == dict(key=['Enter'], literal_writes=1, outcome='observed-submission', composer_typed=False)
    else:
        assert old == new == dict(key=[], literal_writes=0, outcome='unverified', composer_typed=True)
print('PASS: busy first key changes; queue is not delivery; strict retry and foreign-draft guards retained', flush=True)
