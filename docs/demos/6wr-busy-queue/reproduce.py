"""Show the same synthetic queue geometry on base and candidate source."""
import json
import os
from pathlib import Path
import subprocess
import sys


def child(source):
    sys.path.insert(0, source)
    from shantytown import input_box, triage
    for distance in (10, 20):
        for working in (True, False):
            rows = ['• Working (6m 12s • esc to interrupt)' if working else '• Done.',
                    '', '• Queued follow-up inputs', '  ↳ Continue assigned work.']
            rows += ['    wrapped preview'] * (distance - len(rows))
            screen = '\n'.join(rows + ['› Ask Codex to do anything', '',
                                       '  gpt-6 high · /workspace'])
            print(json.dumps(dict(distance=distance, working=working,
                                  triage_busy=triage.mid_flight(screen),
                                  input_busy=input_box._codex_busy(screen))))


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--child':
        child(sys.argv[2])
    else:
        candidate = str(Path(__file__).resolve().parents[3])
        for phase, source in [('before', os.environ['BUSY_QUEUE_BASELINE']),
                              ('after', candidate)]:
            result = subprocess.run([sys.executable, __file__, '--child', source],
                                    check=True, capture_output=True, text=True)
            for line in result.stdout.splitlines():
                row = json.loads(line)
                expected = row['working'] and phase == 'after'
                assert row['triage_busy'] == row['input_busy'] == expected
                print(phase + ': ' + line)
        print('PASS: working queues become busy; idle queues stay idle.')
