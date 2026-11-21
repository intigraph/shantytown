"""Source parser/admission demo. Forge and identity fixtures; no real jobs."""
import io
import hashlib
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = 'a5194aea29f5e417c8dbc810a1f0253b2484f920'
argv = ['agent', 'spawn', '--recruiter', '--ephemeral', '--job', 'review',
        '--item', 'task-1', '--repo', 'intigraph/widget', '--pr', '42',
        '--head', 'a' * 40, '--dry-run']
with tempfile.TemporaryDirectory() as directory:
    archive = subprocess.check_output(['git', 'archive', BASE, 'shantytown'], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        source.extractall(directory, filter='data')
    result = subprocess.run([sys.executable, '-c',
                             'from shantytown.cli import _parse_args; _parse_args(' + repr(argv) + ')'],
                            cwd=directory, env=dict(os.environ, PYTHONPATH=directory),
                            text=True, capture_output=True)
    assert result.returncode == 2, result.stderr
    print('BASE', BASE, result.stderr.strip().splitlines()[-1])
sys.path.insert(0, str(ROOT))
from shantytown.cli import _parse_args
args = _parse_args(argv)
assert args.recruiter and args.dry_run
print('CANDIDATE cli.py SHA256=' + hashlib.sha256((ROOT / 'shantytown/cli.py').read_bytes()).hexdigest())
print('CANDIDATE: scoped qualification flag accepted; dry-run only')
sys.path.insert(0, str(ROOT / 'tests'))
from test_recruiter import admission_fixture
from shantytown import recruiter
from shantytown.actor_identity import IdentityError
req, info, binding, runs, statuses, required, decision, gh, calls = admission_fixture()
recruiter.admit(req, gh=gh, verdict=lambda *args: decision, binding=lambda _: binding)
print('FIXTURE AUTHORITIES: matching custody + exact green head + no verdict -> qualification admitted')
binding['revision'] = 'b' * 40
try:
    recruiter.admit(req, gh=gh, verdict=lambda *args: decision, binding=lambda _: binding)
except IdentityError as error:
    print('SAME PR, DIFFERENT CUSTODY HEAD: refused:', error)
else:
    raise AssertionError('mismatched custody admitted')
# Actual CLI guard control under fake identity/forge adapters and NullPanes.
result = subprocess.run([sys.executable, '-m', 'pytest', '-q',
    'tests/test_ephemeral.py::test_scoped_recruiter_cli_keeps_native_binding_and_management_guards',
    '-k', 'live-handoff', '--disable-warnings'], cwd=ROOT, text=True, capture_output=True)
assert result.returncode == 0, result.stdout + result.stderr
print('ACTUAL CLI CONTROL: live request refused before sudo-capable launcher; no job record or launch')
print('LIMIT: fixture identity/forge data; no installed capability, real attestation or live spawn')
