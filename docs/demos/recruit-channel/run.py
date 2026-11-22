"""Source socket-to-preparation control; no real enrollment or job launch."""
import io
import json
from pathlib import Path
import os
import subprocess
import sys
import tarfile
import tempfile
ROOT = Path(__file__).resolve().parents[3]
BASE = '9d5ca5d2f4b28c54264d1425c1335415ce6208e4'
with tempfile.TemporaryDirectory() as directory:
    archive = subprocess.check_output(['git', 'archive', BASE, 'shantytown'], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        source.extractall(directory, filter='data')
    before = subprocess.run([sys.executable, '-c', 'from shantytown import recruit_channel'],
        cwd=directory, env=dict(os.environ, PYTHONPATH=directory), capture_output=True, text=True)
    assert before.returncode != 0 and 'ImportError' in before.stderr
    print('BASE', BASE, 'connected controller preparation unavailable')
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
import pytest
from shantytown import recruit_channel as channel, recruit_store as rs
from shantytown.actor_identity import IdentityError
from test_recruit_store import private_store
from test_recruit_handoff import ctx as context
from test_recruit_channel import connected
with tempfile.TemporaryDirectory() as directory, pytest.MonkeyPatch.context() as patch:
    private = private_store.__wrapped__(Path(directory), patch)
    ctx = context.__wrapped__(private, patch)
    # Explicit synthetic protected UID enrollment. No host identity is installed.
    patch.setattr(channel, '_peer_uid', lambda _: ctx.pin.uid)
    receipt, observed = connected(ctx)
    assert observed == [receipt]
    print('CANDIDATE real socket -> existing durable preparation:', json.dumps(receipt, sort_keys=True))
    with rs.Store(ctx.pin) as store:
        state = store.db.execute('SELECT state FROM operations').fetchall()
    assert state == [('prepared',)]
    print('REOPENED durable operation:', state[0][0])
    try:
        connected(ctx)
    except IdentityError as error:
        assert 'replay' in str(error)
        print('SAME signed frame on a new connection:', str(error))
    else:
        raise AssertionError('replay accepted')
print('LIMIT: synthetic peer enrollment, key, custody, forge and launch capability; real sockets/store/planner. No listener, installation, native UID probe or job execution.')
