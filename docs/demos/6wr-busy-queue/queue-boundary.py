"""Synthetic quoted queue must not erase later current status."""
import json
import os
from pathlib import Path
import subprocess
import sys

if len(sys.argv) == 2:
    sys.path.insert(0, sys.argv[1])
    from shantytown import input_box, triage
    from shantytown.tmux import NullPanes
    screen = '\n'.join(['Quoted terminal sample follows:',
        'Queued follow-up inputs', '  ↳ Example queued text.', '',
        '• Working (6m 12s • esc to interrupt)', '› typed draft', '',
        '  gpt-6 high · /workspace'])
    panes = NullPanes(screen=screen)
    input_box._SETTLE_S = 0
    result = input_box.clear(panes, 'fixture')
    print(json.dumps(dict(busy=triage.mid_flight(screen),
                         verdict=result.verdict, controls=panes.controls)))
else:
    for phase, source in [('before', os.environ['QUEUE_BOUNDARY_BASELINE']),
                          ('after', str(Path(__file__).resolve().parents[3]))]:
        result = subprocess.run([sys.executable, __file__, source],
                                check=True, capture_output=True, text=True)
        row = json.loads(result.stdout)
        assert row['busy'] == (phase == 'after'), row
        assert len(row['controls']) == (0 if phase == 'after' else 3), row
        print(phase + ': ' + result.stdout.strip())
    print('PASS: later Working remains busy; NullPanes receives zero edit keys.')
