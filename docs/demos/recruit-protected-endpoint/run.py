"""Private fixture demo: synthetic enrollment; real socket/signature/nonce ledger."""
from pathlib import Path
import json
import sys
import tempfile
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'tests'))
from test_recruit_endpoint import context, enrolled, peer, READY
from test_recruitment_request import native
from shantytown import recruit_endpoint as endpoint, recruit_request as rr
from shantytown.actor_identity import IdentityError

print('Fixture only: synthetic root enrollment; real private Unix socket, signature and SQLite ledger.')
try:
    endpoint.exchange(None, policy=SimpleNamespace())
except IdentityError as error:
    print('Default gate:', error)
else:
    raise AssertionError('default gate opened')

with tempfile.TemporaryDirectory(prefix='endpoint-demo-') as directory:
    root = Path(directory)
    fixture = context.__wrapped__(root)
    ctx = next(fixture)
    try:
        with pytest.MonkeyPatch.context() as patch:
            enrollment = enrolled.__wrapped__(ctx, patch)
            _, pin, body = enrollment
            def verify(channel, raw):
                ledger = rr.Ledger(root / 'verified.sqlite')
                try:
                    assert rr.qualify(json.loads(raw), binding=pin, now=110,
                        ledger=ledger, native_binding=native) == body
                finally:
                    ledger.close()
                channel.sendall(b'{"state":"prepared","live":false}')
            result, seen = peer(enrollment, patch,
                lambda envelope, _: endpoint.exchange(envelope, policy=READY), verify)
            assert len(seen) == 1 and result == {'state': 'prepared', 'live': False}
            print('Enabled fixture:', json.dumps(result, sort_keys=True), '; signed frames =', len(seen))
            def wrong_peer(envelope, descriptor):
                descriptor['controller_uid'] += 1
                try:
                    endpoint.exchange(envelope, policy=READY)
                except IdentityError as error:
                    print('Wrong peer:', error)
                else:
                    raise AssertionError('wrong peer accepted')
            _, seen = peer(enrollment, patch, wrong_peer, lambda *_: None)
            assert seen == [b'']
            print('Wrong-peer request bytes:', len(seen[0]))
    finally:
        fixture.close()
print('No production connection, listener installation or job launch.')
