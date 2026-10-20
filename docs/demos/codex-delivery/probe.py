"""Synthetic tmux responses; never attaches to a provider or a real pane."""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from pytest import MonkeyPatch

sys.path.insert(0, str(Path.cwd() / 'tests'))
from test_codex_submission import transport, keys, READY, OWNED, BUSY, QUEUED, BODY
from shantytown.tmux import PaneSubmissionUnverified


for label, frames in [('queued_preview', [BUSY, QUEUED]),
                      ('blocked_enter', [READY, OWNED]),
                      ('human_draft', [OWNED.replace(BODY, 'Human draft')])]:
    with TemporaryDirectory(prefix='codex-delivery-demo-') as directory:
        with MonkeyPatch.context() as patch:
            patch.setenv('SHANTY_ROOT', directory)
            panes, calls = transport(patch, frames)
            patch.setattr(panes, 'session_created', lambda _: 17.0)
            original = panes.capture
            patch.setattr(panes, 'capture', lambda *a, **kw:
                          READY if any(c[-1] == 'C-u' for c in keys(calls))
                          else original(*a, **kw))
            try:
                panes.send('worker', BODY)
                result = 'delivered'
            except PaneSubmissionUnverified:
                result = 'unverified'
            retained = [json.loads(p.read_text())['state'] for p in
                        (Path(directory) / 'delivery').glob('send-*.json')]
            print(json.dumps(dict(case=label, result=result,
                                  keys=[c[-1] for c in keys(calls)],
                                  retained=retained)))
