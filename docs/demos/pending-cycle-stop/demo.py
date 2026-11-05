"""Compare real Stop advice on two revisions using isolated hard-context fixtures."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from shantytown.cycle import Requests
from shantytown.protocols import Agent


def load(revision, index):
    source = subprocess.run(['git', 'show', revision + ':shantytown/stop_policy.py'],
                            check=True, capture_output=True, text=True).stdout
    name = 'shantytown._demo_stop_' + str(index)
    module = types.ModuleType(name)
    module.__package__ = 'shantytown'
    sys.modules[name] = module
    exec(compile(source, 'stop_policy.py@' + revision, 'exec'), module.__dict__)
    return module


def probe(module, pending):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root/'shantytown.toml').write_text('[session_budget]\ncontext_window=1000\ncontext_threshold_pct=70\n')
        transcript = root/'session.jsonl'
        transcript.write_text(json.dumps(dict(message=dict(model='fixture', usage=dict(
            input_tokens=2, cache_read_input_tokens=988, cache_creation_input_tokens=0))))+'\n')
        if pending:
            Requests(root).request('reader', 'saved checkpoint')
        payload = dict(session_id='fixture-session', transcript_path=str(transcript))
        output, diagnostic = io.StringIO(), io.StringIO()
        old_stdin = sys.stdin
        try:
            sys.stdin = io.StringIO(json.dumps(payload))
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(diagnostic):
                module.stop_advice(root, Agent(name='reader', role='worker'))
        finally:
            sys.stdin = old_stdin
        raw = output.getvalue()
        return json.loads(raw)['decision'] if raw else 'ALLOW (no model feedback)'


def main():
    base, head = sys.argv[1:]
    results = []
    for index, revision in enumerate((base, head)):
        module = load(revision, index)
        pending, ordinary = probe(module, True), probe(module, False)
        print(f'{revision}: saved self-cycle + hard context -> {pending}')
        print(f'{revision}: control, no cycle request -> {ordinary}')
        results.append((pending, ordinary))
    assert results == [('block', 'block'), ('ALLOW (no model feedback)', 'block')]
    print('Source fixtures only; no live cycle or lifecycle guard bypass.')


if __name__ == '__main__':
    main()
