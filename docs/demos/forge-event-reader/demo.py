"""Offline before/after reader controls; no network or tracker writes."""
import importlib.util
from pathlib import Path
import subprocess
import types

ROOT = Path(__file__).resolve().parents[3]
BASE = 'a2afbdf4660908757245f349b826d5707c6e22f9'
SHA = 'a' * 40
old = types.ModuleType('before')
exec(compile(subprocess.check_output(
    ['git', 'show', BASE + ':shantytown/resume_forge_events.py'], cwd=ROOT),
    'base-reader', 'exec'), old.__dict__)
spec = importlib.util.spec_from_file_location('after', ROOT / 'shantytown/resume_forge_events.py')
new = importlib.util.module_from_spec(spec)
spec.loader.exec_module(new)


def fixture(native=False, hidden_pending=False):
    def read(forge, repo, path):
        if path.startswith('actions/runs?'):
            return {'total_count': 1, 'workflow_runs': [dict(
                id=1, workflow_id='ci.yml', event='' if native else 'push',
                trigger_event='push', commit_sha=SHA, status='success')]}
        if hidden_pending:
            if path.endswith('page=1'):
                return [dict(id=i + 2, context='done-' + str(i), status='success')
                        for i in range(50)]
            return [dict(id=100, context='late', status='pending')]
        return []
    return read


print('Offline fixture; base ' + BASE + '; candidate reader from this checkout')
for label, reader, expected in (
    ('Native trigger_event, empty legacy event', fixture(native=True), (None, True)),
    ('Pending context on status page two', fixture(hidden_pending=True), (True, False)),
):
    answers = []
    print('\n' + label)
    for name, module in (('before', old), ('after', new)):
        answer, why = module.evaluate('ci-terminal', 'forgejo/example/project@' + SHA, read=reader)
        answers.append(answer)
        print(f'{name}: {answer!r} ({why})')
    assert tuple(answers) == expected
print('\nControls PASS. Terminal is a wake condition, never permission to merge.')
