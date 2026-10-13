"""Synthetic transport proof: one durable body stranded behind a busy turn."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from shantytown import tmux

base = sys.argv[1]
old = subprocess.check_output(['git', 'show', f'{base}:shantytown/tmux.py'], text=True)
body = '[from reviewer] Review the assigned source packet.'
footer = '  gpt-6 high · /workspace'
ready = '\x1b[1m›\x1b[0m \x1b[2mAsk Codex to do anything\x1b[0m\n' + footer
owned = 'Working (1s • esc to interrupt)\n\x1b[1m›\x1b[0m ' + body + '\n' + footer
queued = ('Working (1s • esc to interrupt)\nMessages to be submitted after next tool call\n  ↳ '
          + body + '\n' + ready)
with tempfile.TemporaryDirectory() as tmp:
    source = Path(tmp, 'base.py')
    source.write_text(old)
    spec = importlib.util.spec_from_file_location('shantytown._demo_base', source)
    baseline = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = baseline
    spec.loader.exec_module(baseline)
    for label, mod in [('BASE', baseline), ('HEAD', tmux)]:
        calls = []
        mod._CODEX_POLLS = 2
        mod._CODEX_ATTEMPTS = 2
        mod.time.sleep = lambda _: None
        mod._journal_send = lambda *_: None
        panes = mod.Tmux()
        state = [owned]
        panes.capture = lambda *_a, **_k: state[0]
        panes.foreground = lambda _: 'codex'
        def run(args, **kw):
            calls.append(args)
            if args[-1] == 'Tab':
                state[0] = queued
        mod.subprocess.run = run
        try:
            panes.send('worker', body)
            outcome = 'confirmed queue'
        except mod.PaneSubmissionUnverified:
            outcome = 'UNVERIFIED; input remains stranded'
        submitted = sum(args[-1] == 'Tab' for args in calls)
        print(f'{label}: {outcome}; queued={submitted}; body writes={sum("-l" in args for args in calls)}')
        assert submitted == (label == 'HEAD')
        assert not any('-l' in args for args in calls)
print('Foreign text, changed runtime, empty composer, duplicate pointers and store errors: covered by independent regression controls.')
