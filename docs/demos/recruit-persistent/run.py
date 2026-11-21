"""Protected fixture store + launch admission; no host policy or live jobs."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[3]
BASE = 'fd10adc776c214200f1f143f45352123c0354044'
PROBE = r'''
from shantytown import recruit_request as r
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
key=Ed25519PrivateKey.generate()
pin=r.Binding('fixture-recruiter',10001,'fixture-host',('intigraph/widget',),key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw))
body=dict(schema=r.SCHEMA,principal=pin.principal,uid=pin.uid,host=pin.host,verb='launch',job='review',item='task-1',repo='intigraph/widget',pr=42,head='a'*40,target=None,nonce='b'*64,issued_at=100,expires_at=160)
envelope=dict(body=body,signature=key.sign(r.message(body)).hex())
def native(item):
 envelope['body']['head']='f'*40
 return dict(schema='chaski.github.work-request/v1',kind='review',repo='intigraph/widget',revision='a'*40,facts={'pr':42})
ledger=r.Ledger(':memory:')
try:
 result=r.qualify(envelope,binding=pin,now=110,ledger=ledger,native_binding=native)
 print('signed head='+('a'*40)+'; callback changes caller head='+('f'*40)+'; verified result='+result['head'])
finally:ledger.close()
'''
with tempfile.TemporaryDirectory() as directory:
    archive = subprocess.check_output(['git', 'archive', BASE, 'shantytown'], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        source.extractall(directory, filter='data')
    before = subprocess.check_output([sys.executable, '-c', PROBE], cwd=directory,
                                    env=dict(os.environ, PYTHONPATH=directory), text=True)
    assert 'verified result=' + 'f'*40 in before
    print('BASE', BASE, before.strip())
after = subprocess.check_output([sys.executable, '-c', PROBE], cwd=ROOT,
                               env=dict(os.environ, PYTHONPATH=str(ROOT)), text=True)
assert 'verified result=' + 'a'*40 in after
print('CANDIDATE', after.strip())
for name in ('recruit_request.py', 'recruit_controller.py', 'recruit_store.py', 'recruit_handoff.py'):
    print('CANDIDATE', name, 'SHA256='+hashlib.sha256((ROOT/'shantytown'/name).read_bytes()).hexdigest())
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
import pytest
from test_recruit_store import private_store
from test_recruit_handoff import ctx as context
from shantytown import recruit_handoff as handoff, recruit_store as store
from shantytown.actor_identity import IdentityError
with tempfile.TemporaryDirectory() as directory, pytest.MonkeyPatch.context() as patch:
    # Explicit synthetic enrollment, forge/custody/capability/governor and outer
    # ancestry fixtures. Production Store has no test-path exception.
    private = private_store.__wrapped__(Path(directory), patch)
    ctx = context.__wrapped__(private, patch)
    receipt = handoff.prepare(ctx.signed(), **ctx.kwargs)
    print('FIXTURE durable state -> existing planner/UID/gates:', json.dumps(receipt, sort_keys=True))
    assert receipt['nonce_durable'] and receipt['execution'] == 'refused'
    try:
        handoff.prepare(ctx.signed(), **ctx.kwargs)
    except IdentityError as error:
        print('REOPENED store, same request:', str(error))
    else: raise AssertionError('replay admitted')
    path = ctx.directory / store.NAME
    retained = ctx.directory.parent / 'retained-fixture.sqlite3'
    path.rename(retained)
    path.symlink_to(retained)
    try:
        store.Store(ctx.pin)
    except IdentityError as error:
        print('SAME state path replaced with symlink:', str(error))
    else: raise AssertionError('symlink admitted')
print('LIMIT: fixture identities/authority/capabilities. No CLI activation, native UID drop, privileged call, job/card/pane or host enrollment.')
