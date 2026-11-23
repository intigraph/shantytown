"""Isolated source API probe. No panes, processes or production calls."""
import ast
import hashlib
import subprocess
from pathlib import Path
from types import SimpleNamespace
from shantytown import cli, ephemeral, harness
from shantytown.protocols import Agent, SubmissionObserved

BASE = 'e0a982d8fb74fafe870e2c6ad88c3b6d54b41188'
current = cli._deliver_startup_inbox
before = subprocess.check_output(['git', 'show', BASE + ':shantytown/cli.py'], text=True)
node = next(n for n in ast.parse(before).body if isinstance(n, ast.FunctionDef)
            and n.name == '_deliver_startup_inbox')
namespace = dict(cli.__dict__)
exec(compile(ast.Module(body=[node], type_ignores=[]), '<base>', 'exec'), namespace)
card = Agent(name='eph-review-abc123', role='worker', harness='codex')
ephemeral.read = lambda *a: {'name': card.name}
ephemeral.prompt = lambda rec: 'perform the fixture job'
harness.name_for = lambda *a, **kw: 'codex'
cli.time.sleep = lambda _: None

class Pane:
    def __init__(self, frames):
        self.frames, self.looks, self.sent = frames, 0, 0
    def capture(self, *a, **kw):
        frame = self.frames[min(self.looks, len(self.frames)-1)]
        self.looks += 1
        return {'busy': 'Working (1s) · Running hooks\n› \n  model · esc to interrupt',
                'idle': '› \n  model · context left',
                'foreign': '› operator note\n  model · context left'}[frame]
    def send(self, pane, text):
        self.sent += 1
        if not self.looks or self.frames[min(self.looks-1, len(self.frames)-1)] != 'idle':
            raise RuntimeError('startup turn is busy or composer foreign')
        return SubmissionObserved(pane, hashlib.sha256(text.encode()).hexdigest())

print('Same synthetic pane frames on base and candidate; no real job spawned.')
print('candidate source blob:', subprocess.check_output(
    ['git','hash-object','shantytown/cli.py'],text=True).strip())
for label, function in [('base '+BASE, namespace['_deliver_startup_inbox']), ('candidate', current)]:
    for frames in [['busy','busy','idle'], ['foreign'], ['busy']]:
        args, pane = SimpleNamespace(root=Path('/fixture')), Pane(frames)
        delivered = bool(function(args, card, pane, 'fixture-pane'))
        print(label, '/'.join(frames), 'delivered='+str(delivered),
              'send_calls='+str(pane.sent), 'observations='+str(pane.looks))
        if label == 'candidate':
            assert delivered == (frames[-1] == 'idle')
            assert pane.sent == int(delivered)
