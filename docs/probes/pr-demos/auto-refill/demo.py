"""Local library fixture; no real panes, tracker, registry or network writes."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types

root = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(root))
from shantytown import triage
from shantytown.dispatch import Dispatcher
from shantytown.files import FilesRegistry, FilesTracker
from shantytown.refill import Refiller
from shantytown.tmux import NullPanes

baseline = sys.argv[1] if len(sys.argv) > 1 else 'a5275a8'
source = subprocess.check_output(['git', 'show', baseline + ':shantytown/triage.py'], cwd=root)
old = types.ModuleType('shantytown._demo_baseline')
old.__package__ = 'shantytown'
sys.modules[old.__name__] = old
exec(compile(source, '<baseline triage>', 'exec'), old.__dict__)
body = '\n'.join('Retained machine notice line ' + str(i) for i in range(12))
screen = ('\x1b[1m›\x1b[0m ' + body + '\n\n'
          '  GPT-6.1-Sol default · /workspace · Review work\n'
          '                                     ⚠ 1 warning · f2 to view')
print('Fixture: identical owned-notice frame, with warning replacing shortcuts')
print('Before:', baseline, old.input_state(screen))
print('After: candidate', triage.input_state(screen))
assert old.input_state(screen) != triage.INPUT_QUEUED
assert triage.input_state(screen) == triage.INPUT_QUEUED

with tempfile.TemporaryDirectory() as directory:
    home = Path(directory)
    crew = home / 'crew'
    crew.mkdir()
    (crew / 'author.json').write_text(json.dumps(
        dict(role='worker', reports_to='chief', pane='%5')))
    registry = FilesRegistry(crew)
    tracker = FilesTracker(home / 'items')
    tracker.update('ready-task', title='Implement a library feature', status='open')
    panes = NullPanes()
    dispatcher = Dispatcher(registry, tracker, panes)
    candidate = dict(id='ready-task', title='Implement a library feature',
                     status='open', priority=1, labels=[])
    print('Fixture: one idle author, one unassigned ready task')
    print('Before tick:', tracker.get('ready-task').status,
          'owner=' + (tracker.get('ready-task').assignee or '<none>'))
    def dispatch(item, worker):
        dispatcher.go(item, worker)
        return 0
    refill = Refiller(home, registry, panes, None, snapshot=lambda: ([candidate], []),
        preview=lambda item, worker: bool(dispatcher.go(item, worker, dry_run=True)),
        dispatch=dispatch, free=lambda: ['author'])
    assert refill.sweep() == ['author']
    actual = tracker.get('ready-task')
    print('After tick:', actual.status, 'owner=' + actual.assignee,
          'normal-dispatch messages=' + str(len(panes.sent)))
    assert actual.status == 'in_progress' and actual.assignee == 'author'
    assert len(panes.sent) == 1
print('PASS: source fixture only; installed and 24-hour acceptance remain separate')
