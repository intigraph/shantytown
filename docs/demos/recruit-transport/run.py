"""Source-only bounded Unix-channel demonstration, with synthetic authority."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[3]
BASE = '6c115c7fa034d46965201f98219ef7627e5cef4b'
with tempfile.TemporaryDirectory() as directory:
    archive = subprocess.check_output(['git', 'archive', BASE, 'shantytown'], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        source.extractall(directory, filter='data')
    before = subprocess.run([sys.executable, '-c', 'from shantytown import recruit_transport'],
                            cwd=directory, env=dict(os.environ, PYTHONPATH=directory),
                            capture_output=True, text=True)
    assert before.returncode != 0 and 'ImportError' in before.stderr
    print('BASE', BASE, 'bounded connected-channel helper unavailable')

sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from test_recruitment_request import context, signed, native
from test_recruit_transport import run_peer
from shantytown import recruit_request as rr, recruit_transport as transport
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory)
    fixture = context.__wrapped__(path)
    key, pin, body, _ = next(fixture)
    envelope = signed(key, body)
    def controller(server, raw):
        ledger = rr.Ledger(path / 'controller.sqlite')
        try:
            checked = rr.qualify(json.loads(raw), binding=pin, now=110,
                                 ledger=ledger, native_binding=native)
            assert checked == body
        finally:
            ledger.close()
        server.sendall(b'{"live":false,"execution":"refused"}')
    result, sent = run_peer(envelope, controller)
    assert len(sent) == 1
    print('CANDIDATE one real Unix exchange + existing signature verifier:', json.dumps(result))
    try:
        run_peer(envelope, lambda server, raw: server.sendall(b'{'))
    except transport.DeliveryUnknown as error:
        print('LOST/MALFORMED RESPONSE:', str(error), '(no automatic retry)')
    else:
        raise AssertionError('malformed output accepted')
    ledger = rr.Ledger(path / 'controller.sqlite')
    try:
        try:
            rr.qualify(envelope, binding=pin, now=110, ledger=ledger, native_binding=native)
        except Exception as error:
            assert str(error) == 'recruitment replay refused'
            print('ORIGINAL NONCE after reopen:', str(error))
        else:
            raise AssertionError('replay accepted')
    finally:
        ledger.close()
        fixture.close()
print('LIMIT: synthetic key/custody/controller response; real local sockets and verifier. No endpoint install, listener, daemon, privilege or job launch. Existing live refusal remains.')
