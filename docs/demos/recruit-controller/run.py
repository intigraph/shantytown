"""Source-only controller preview: synthetic identity/forge; no live calls."""
import hashlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
BASE = 'ac947ac9febea9e43e6f5e6d8fa488c1fc101414'
argv = ['agent', 'spawn', '--recruitment-request', '--dry-run', '--json']
with tempfile.TemporaryDirectory() as directory:
    archive = subprocess.check_output(['git', 'archive', BASE, 'shantytown'], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        source.extractall(directory, filter='data')
    result = subprocess.run([sys.executable, '-c',
                             'from shantytown.cli import build_parser; build_parser().parse_args(' + repr(argv) + ')'],
                            cwd=directory, env=dict(os.environ, PYTHONPATH=directory),
                            capture_output=True, text=True)
    assert result.returncode == 2
    print('BASE', BASE, result.stderr.strip().splitlines()[-1])
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from test_recruiter import admission_fixture
from shantytown import cli, config, recruit_controller as rc, recruit_request as rr, recruiter
from shantytown.actor_identity import IdentityError
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
for file in ('cli.py', 'recruit_controller.py', 'recruit_request.py'):
    print('CANDIDATE', file, 'SHA256=' + hashlib.sha256((ROOT / 'shantytown' / file).read_bytes()).hexdigest())
with tempfile.TemporaryDirectory() as directory:
    key = Ed25519PrivateKey.generate()
    pin = rr.Binding('fixture-recruiter', 10001, 'fixture-host', ('intigraph/widget',),
                     key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw), directory)
    body = dict(schema=rr.SCHEMA, principal=pin.principal, uid=pin.uid, host=pin.host,
                verb='launch', job='review', item='task-1', repo='intigraph/widget', pr=42,
                head='a'*40, target=None, nonce='b'*64, issued_at=100, expires_at=160)
    envelope = {'body': body, 'signature': key.sign(rr.message(body)).hex()}
    _, _, custody, _, _, _, decision, gh, _ = admission_fixture()
    cfg = config.Config(host_name=pin.host)
    cfg = replace(cfg, ephemeral=replace(cfg.ephemeral, require_verified_identity=True))
    roles = SimpleNamespace(get=lambda name: SimpleNamespace(role='administrator'))
    def admit(request, **kwargs):
        recruiter.admit(request, gh=gh, verdict=lambda *a: decision, binding=lambda item: custody)
    receive = rc.receive
    with patch.object(cli.config, 'load_or_default', return_value=(cfg, None)), \
         patch.object(cli, 'FilesRegistry', return_value=roles), \
         patch.object(cli, '_spawn_actor', return_value='fixture-admin'), \
         patch.object(cli, '_spawn_inside', return_value=None), \
         patch.object(cli, '_spawn_item_work_request', return_value=custody), \
         patch.object(rr, 'load_controller_binding', return_value=pin), \
         patch.object(rc.os, 'geteuid', return_value=10002), \
         patch.object(rc.socket, 'gethostname', return_value=pin.host), \
         patch.object(rc, 'read_input', return_value=envelope), \
         patch.object(rc.recruiter, 'cli_admit', side_effect=admit), \
         patch.object(rc, 'receive', side_effect=lambda *a, **kw: receive(*a, **kw, clock=lambda: 110)):
        print('CANDIDATE same CLI input, signed fixture + fresh fixture authorities:')
        args = cli.build_parser().parse_args(['--root', directory, *argv])
        assert cli._cmd_spawn(args) == 0
        print('NO --dry-run: expected refusal before reading a request')
        args = cli.build_parser().parse_args(['--root', directory, 'agent', 'spawn', '--recruitment-request'])
        assert cli._cmd_spawn(args) == 1
        ledger = rr.Ledger(Path(directory) / 'private-fixture.sqlite')
        try:
            kw = dict(policy=cfg.ephemeral, actor='fixture-admin', inside=None,
                      role_of=lambda name: 'administrator', root=directory, host=pin.host,
                      ledger=ledger, native_binding=lambda item: custody, admit=admit, clock=lambda: 110)
            receive(envelope, **kw)
            try:
                receive(envelope, **kw)
            except IdentityError as error:
                print('DURABLE FIXTURE same nonce:', str(error))
            else:
                raise AssertionError('replay admitted')
        finally:
            ledger.close()
print('LIMIT: source preview only; fixture identity/key/forge/custody. No installed binding, state, privileged call or live job.')
