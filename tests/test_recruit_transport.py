"""Real local Unix channels; synthetic keys/custody, no listener or launcher."""
import json
import os
import socket
import threading
import time

import pytest

from shantytown.actor_identity import IdentityError
from shantytown import recruit_transport as transport, recruit_request as rr
from test_recruitment_request import context, signed, native  # noqa: F401

pytestmark = pytest.mark.skipif(not hasattr(socket, 'SO_PEERCRED'), reason='Linux peer credentials')


def run_peer(envelope, responder, **options):
    client, server = socket.socketpair()
    seen = []
    errors = []

    def serve():
        try:
            with server:
                server.settimeout(1)
                raw = bytearray()
                while chunk := server.recv(4096):
                    raw.extend(chunk)
                seen.append(bytes(raw))
                responder(server, bytes(raw))
        except (BrokenPipeError, ConnectionResetError):
            pass  # A bounded client may already have refused and closed.
        except Exception as error:
            errors.append(error)

    thread = threading.Thread(target=serve)
    thread.start()
    try:
        with client:
            return transport.exchange(client, envelope, peer_uid=os.getuid(), **options), seen
    finally:
        thread.join(2)
        assert not thread.is_alive()
        assert not errors


def test_real_channel_preserves_signed_body_and_uses_existing_verifier(context, tmp_path):
    key, pin, body, _ = context
    envelope = signed(key, body)
    path = tmp_path / 'controller.sqlite'

    def controller(server, raw):
        ledger = rr.Ledger(path)
        try:
            verified = rr.qualify(json.loads(raw), binding=pin, now=110,
                                  ledger=ledger, native_binding=native)
        finally:
            ledger.close()
        assert verified == body
        server.sendall(b'{"live":false,"execution":"refused"}')

    result, seen = run_peer(envelope, controller)
    assert result == {'live': False, 'execution': 'refused'}
    assert len(seen) == 1 and json.loads(seen[0]) == envelope
    ledger = rr.Ledger(path)
    try:
        with pytest.raises(IdentityError, match='replay'):
            rr.qualify(envelope, binding=pin, now=110, ledger=ledger, native_binding=native)
    finally:
        ledger.close()


def test_wrong_peer_refuses_before_sending(context):
    key, _, body, _ = context
    client, server = socket.socketpair()
    with client, server:
        with pytest.raises(IdentityError, match='peer UID mismatch'):
            transport.exchange(client, signed(key, body), peer_uid=os.getuid() + 1)
        server.setblocking(False)
        with pytest.raises(BlockingIOError):
            server.recv(1)


@pytest.mark.parametrize('change', [{'job': 'merge'}, {'verb': 'merge'}, {'extra': 'x'},
                                  {'item': 'x' * 8192}])
def test_invalid_input_never_enters_io(context, change):
    key, _, body, _ = context
    envelope = {'body': body | change, 'signature': 'a' * 128}
    with pytest.raises(IdentityError):
        transport.exchange(None, envelope, peer_uid=os.getuid())


@pytest.mark.parametrize('output', [b'', b'{', b'{"x":1,"x":2}', b'x' * 8193])
def test_lost_or_unbounded_response_is_unknown_without_retry(context, output):
    key, _, body, _ = context
    with pytest.raises(transport.DeliveryUnknown, match='preserve attempt and nonce'):
        run_peer(signed(key, body), lambda server, raw: server.sendall(output))


def test_total_deadline_rejects_slow_drip_not_just_idle_reads(context):
    key, _, body, _ = context

    def drip(server, raw):
        for byte in b'{"ok":true}':
            server.sendall(bytes([byte]))
            time.sleep(0.025)

    start = time.monotonic()
    with pytest.raises(transport.DeliveryUnknown):
        run_peer(signed(key, body), drip, timeout=0.08)
    assert time.monotonic() - start < 1


@pytest.mark.parametrize('timeout', [True, 0, -1, 6, float('inf'), float('nan')])
def test_invalid_deadline_refuses_before_io(context, timeout):
    key, _, body, _ = context
    with pytest.raises(IdentityError, match='channel or budget'):
        transport.exchange(None, signed(key, body), peer_uid=os.getuid(), timeout=timeout)
