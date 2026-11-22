"""Connected preparation; synthetic protected identity, real socket/store gates."""
from dataclasses import replace
import os
import socket
import threading
import time

import pytest

from shantytown.actor_identity import IdentityError
from shantytown import recruit_channel as channel, recruit_transport as transport
from shantytown import recruit_request as rr, recruit_store as rs, recruit_handoff as handoff
from test_recruit_handoff import ctx  # noqa: F401
from test_recruit_store import private_store  # noqa: F401


def connected(ctx, *, kwargs=None, timeout=1):
    client, server = socket.socketpair()
    observed = []

    def send():
        with client:
            try:
                observed.append(transport.exchange(client, ctx.signed(), peer_uid=os.getuid()))
            except Exception as error:
                observed.append(error)

    worker = threading.Thread(target=send)
    worker.start()
    try:
        with server:
            return channel.prepare_connected(server, timeout=timeout,
                                             **(ctx.kwargs if kwargs is None else kwargs)), observed
    finally:
        worker.join(2)
        assert not worker.is_alive()


@pytest.fixture
def synthetic_peer(ctx, monkeypatch):
    # Real protected-UID installation is activation work. All positive tests
    # explicitly substitute peer enrollment; the real mismatch control below
    # exercises the kernel credentials without this fixture.
    monkeypatch.setattr(channel, '_peer_uid', lambda _: ctx.pin.uid)
    return ctx


def test_real_peer_credentials_refuse_before_read_or_nonce(ctx):
    client, server = socket.socketpair()
    with client, server:
        assert channel._peer_uid(server) == os.getuid()
        with pytest.raises(IdentityError, match='recruiter UID mismatch'):
            channel.prepare_connected(server, **ctx.kwargs)
    assert not list(ctx.directory.iterdir()) and not ctx.calls


def test_connected_prepare_verifies_and_spends_nonce_but_never_launches(synthetic_peer, monkeypatch):
    ctx = synthetic_peer
    def forbidden(*args, **kwargs):
        pytest.fail('connected preparation attempted launch/lifecycle')
    for name in ('execute', 'probe', 'stop', 'stop_native', 'command'):
        monkeypatch.setattr(handoff.job_launch, name, forbidden)
    receipt, observed = connected(ctx)
    assert observed == [receipt]
    assert receipt['execution'] == 'refused' and receipt['live'] is False
    assert ctx.calls == ['admit', 'select', 'select']
    with rs.Store(ctx.pin) as store:
        assert store.db.execute('SELECT state FROM operations').fetchall() == [('prepared',)]
    with pytest.raises(IdentityError, match='replay'):
        connected(ctx)
    assert ctx.calls == ['admit', 'select', 'select']


def test_independent_controller_authority_before_peer_binding_or_input(ctx, monkeypatch):
    def forbidden():
        pytest.fail('binding read before controller authority')
    monkeypatch.setattr(rr, 'load_controller_binding', forbidden)
    with pytest.raises(IdentityError):
        channel.prepare_connected(None, **(ctx.kwargs | {'inside': 'untrusted-pane'}))


@pytest.mark.parametrize('raw', [b'', b'{', b'{"body":{},"body":{}}', b'x' * 8193])
def test_invalid_frame_before_durable_admission(synthetic_peer, raw):
    ctx = synthetic_peer
    client, server = socket.socketpair()
    with client, server:
        client.sendall(raw)
        client.shutdown(socket.SHUT_WR)
        with pytest.raises(IdentityError, match='frame refused'):
            channel.prepare_connected(server, **ctx.kwargs)
    assert not list(ctx.directory.iterdir()) and not ctx.calls


def test_binding_replaced_during_frame_read_refuses_before_nonce(synthetic_peer, monkeypatch):
    ctx = synthetic_peer
    pins = iter([ctx.pin, replace(ctx.pin, public_key=b'z' * 32)])
    monkeypatch.setattr(rr, 'load_controller_binding', lambda: next(pins))
    with pytest.raises(IdentityError, match='binding changed'):
        connected(ctx)
    assert not list(ctx.directory.iterdir()) and not ctx.calls


def test_lost_response_does_not_retract_prepared_state(synthetic_peer):
    import json
    ctx = synthetic_peer
    client, server = socket.socketpair()
    client.sendall(json.dumps(ctx.signed()).encode())
    client.close()
    with server, pytest.raises(transport.DeliveryUnknown, match='retain durable state'):
        channel.prepare_connected(server, **ctx.kwargs)
    with rs.Store(ctx.pin) as store:
        assert store.db.execute('SELECT state FROM operations').fetchall() == [('prepared',)]
    with pytest.raises(IdentityError, match='replay'):
        handoff.prepare(ctx.signed(), **ctx.kwargs)


def test_late_admission_keeps_state_and_refuses_late_reply(synthetic_peer):
    ctx = synthetic_peer
    def slow_governor(_):
        time.sleep(0.08)
        return ''
    with pytest.raises(transport.DeliveryUnknown):
        connected(ctx, kwargs=ctx.kwargs | {'governor': slow_governor}, timeout=0.04)
    with rs.Store(ctx.pin) as store:
        assert store.db.execute('SELECT state FROM operations').fetchall() == [('prepared',)]


def test_frame_without_eof_expires_before_preparation(synthetic_peer):
    ctx = synthetic_peer
    client, server = socket.socketpair()
    with client, server:
        client.sendall(b'{')
        with pytest.raises(IdentityError, match='frame refused'):
            channel.prepare_connected(server, timeout=0.03, **ctx.kwargs)
    assert not list(ctx.directory.iterdir()) and not ctx.calls
