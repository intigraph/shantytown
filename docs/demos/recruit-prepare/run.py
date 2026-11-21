"""Actual parser before/after and isolated durable CLI qualification fixture."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[3]
BASE = 'abebe316dbffb0aba3688571de1c145e043ad457'
with tempfile.TemporaryDirectory() as directory:
    archive = subprocess.check_output(['git', 'archive', BASE, 'shantytown'], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        source.extractall(directory, filter='data')
    probe = "from shantytown.cli import build_parser; build_parser().parse_args(['agent','spawn','--recruitment-prepare','--dry-run'])"
    before = subprocess.run([sys.executable, '-c', probe], cwd=directory,
                            env=dict(os.environ, PYTHONPATH=directory), capture_output=True, text=True)
    assert before.returncode == 2 and '--recruitment-prepare' not in before.stderr and 'is required' in before.stderr
    print('BASE', BASE, 'parser refuses --recruitment-prepare (exit 2)')
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
import pytest
from test_recruit_store import private_store
from test_recruit_handoff import ctx as context
from shantytown import cli, recruit_handoff as handoff
from contextlib import redirect_stdout, redirect_stderr
with tempfile.TemporaryDirectory() as directory, pytest.MonkeyPatch.context() as patch:
    private = private_store.__wrapped__(Path(directory), patch)
    ctx = context.__wrapped__(private, patch)
    patch.setattr(handoff.recruit_controller, 'read_input', ctx.signed)
    args = cli.build_parser().parse_args(['--root', ctx.pin.root, 'agent', 'spawn',
                                         '--recruitment-prepare', '--dry-run', '--json'])
    kw = dict(ctx.kwargs);kw.pop('root')
    out = io.StringIO()
    with redirect_stdout(out): code = handoff.cli_prepare(args, **kw)
    receipt = json.loads(out.getvalue())
    assert code == 0 and receipt['nonce_durable'] and receipt['execution'] == 'refused'
    print('CANDIDATE explicit durable preparation:', json.dumps(receipt, sort_keys=True))
    err = io.StringIO()
    with redirect_stderr(err): code = handoff.cli_prepare(args, **kw)
    assert code == 1 and 'IdentityError' in err.getvalue()
    print('REOPENED same signed frame:', err.getvalue().strip(), 'exit', code)
print('LIMIT: synthetic controller enrollment/custody/forge/capability; private fixture state. No live listener, native UID probe, job or privileged launch.')
