"""Synthetic protocol demo. Pane reads, keys and journal writes are mocked."""
import argparse
import subprocess
from unittest.mock import patch

from shantytown import tmux

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--revision', required=True)
args = parser.parse_args()
source = subprocess.check_output(
    ['git', 'show', args.revision + ':shantytown/tmux.py'], text=True)
exec(compile(source, '<revision tmux.py>', 'exec'), tmux.__dict__)
body = 'Synthetic delivery control.'
footer = '\n\x1b[2mGPT-6.1\x1b[0m\n\x1b[1m? for shortcuts\x1b[0m\n'
ready = '\x1b[1m›\x1b[0m \x1b[2mAsk Codex\x1b[0m' + footer
busy = 'Working (esc to interrupt)\n' + ready
owned = 'Working (esc to interrupt)\n\x1b[1m›\x1b[0m ' + body + footer
queued = ('Working (esc to interrupt)\nMessages to be submitted after next tool call\n'
          '  ↳ ' + body + '\n' + ready)
print('Synthetic library fixture; no real pane keys or journal writes.')
print('Revision:', subprocess.check_output(['git', 'rev-parse', args.revision], text=True).strip())
for label, fresh in [('owned busy composer', owned), ('foreign composer', owned.replace(body, 'Other input'))]:
    pane = tmux.Tmux()
    frames = iter([busy, fresh, queued])
    last = [queued]
    calls = []

    def capture(*_a, **_kw):
        last[0] = next(frames, last[0])
        return last[0]

    with patch.object(pane, 'capture', capture), \
            patch.object(pane, 'foreground', return_value='codex'), \
            patch.object(pane, '_refuse_in_mode'), \
            patch.object(tmux, '_journal_send'), \
            patch.object(tmux, '_CODEX_POLLS', 2), \
            patch.object(tmux.time, 'sleep'), \
            patch.object(tmux.subprocess, 'run', side_effect=lambda argv, **kw: calls.append(argv)):
        try:
            pane._send('synthetic-fixture', body)
            result = 'DELIVERED'
        except tmux.PaneSubmissionUnverified:
            result = 'UNVERIFIED'
    keys = [c[-1] for c in calls if 'send-keys' in c and '-l' not in c]
    print(label + ': keys=' + repr(keys) + ', result=' + result)
