"""Replay modern idle queue through real custody supervision, with fake panes."""
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import pytest

root = Path(sys.argv[1]).resolve()
sys.path[:0] = [str(root), str(root / 'tests')]
from test_delivery_custody import fixtures, observe, records
from test_codex_submission import BODY, READY, keys
from shantytown.events import FilesEvents

screen = ('• Queued follow-up inputs\n  ↳ ' + BODY +
          '\n    shift+← edit last queued message\n' + READY)
with TemporaryDirectory() as folder, pytest.MonkeyPatch.context() as patch:
    target = Path(folder)
    f = fixtures(target, patch, messages=[BODY])
    observe(target, f, screen, 1000)
    print('Idle pane with visible modern queue:')
    print('  custody:', ', '.join(r['state'] for r in records(target)))
    print('  lead events:', len(FilesEvents(target / 'events').pending('lead')))
    print('  unread pointers:', len(f[-1].unread('worker')))
    print('  pane keystrokes:', len(keys(f[1])))
