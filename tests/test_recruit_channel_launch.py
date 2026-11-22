"""Real connected socket/signature/store/spawn; synthetic enrollment/launcher."""
from dataclasses import replace
import json
import os
import socket
import threading
import time

import pytest

from shantytown import recruit_channel as channel, recruit_transport as transport
from shantytown import cli, recruit_handoff as handoff, recruit_store as rs
from shantytown import recruit_request as rr
from shantytown.actor_identity import IdentityError
from test_recruit_launch import native, ctx, private_store  # noqa: F401


def exchange(native, monkeypatch, *, envelope=None, timeout=1):
    monkeypatch.setattr(channel, '_peer_uid', lambda _: native.pin.uid)
    sender, receiver = socket.socketpair()
    observed = []

    def send():
        with sender:
            try:
                observed.append(transport.exchange(sender,
                    native.signed() if envelope is None else envelope, peer_uid=os.getuid()))
            except Exception as error:
                observed.append(error)

    worker = threading.Thread(target=send)
    worker.start()
    try:
        with receiver:
            result = channel.launch_connected(receiver, args=native.args,
                                              timeout=timeout, **native.kwargs)
        return result, observed
    finally:
        worker.join(2)
        assert not worker.is_alive()


def test_signed_connected_request_enters_existing_spawn_once(native, monkeypatch):
    result, observed = exchange(native, monkeypatch)
    assert observed == [result]
    assert result['state'] == 'launched' and result['live'] is True
    assert len(native.launched) == 1
    with rs.Store(native.pin) as store:
        assert store.db.execute('SELECT state FROM operations').fetchall() == [('launched',)]
    with pytest.raises(IdentityError, match='replay'):
        exchange(native, monkeypatch)
    assert len(native.launched) == 1


def test_launch_gate_precedes_channel_or_store_access(native, monkeypatch):
    native.kwargs['policy'] = replace(native.kwargs['policy'], recruitment_launch_ready=False)
    def forbidden(*args, **kwargs):
        pytest.fail('channel touched before activation gate')
    monkeypatch.setattr(channel, '_peer_uid', forbidden)
    with pytest.raises(IdentityError, match='activation is gated'):
        channel.launch_connected(None, args=native.args, **native.kwargs)
    assert not list(native.directory.iterdir()) and not native.launched


def test_real_wrong_peer_refuses_before_nonce(native):
    sender, receiver = socket.socketpair()
    with sender, receiver, pytest.raises(IdentityError, match='UID mismatch'):
        channel.launch_connected(receiver, args=native.args, **native.kwargs)
    assert not list(native.directory.iterdir()) and not native.launched


def test_binding_change_between_channel_and_launch_refuses_before_store(native, monkeypatch):
    pins = iter([native.pin, native.pin, replace(native.pin, uid=native.pin.uid + 1)])
    monkeypatch.setattr(rr, 'load_controller_binding', lambda: next(pins))
    with pytest.raises(IdentityError, match='changed after peer authentication'):
        exchange(native, monkeypatch)
    assert not list(native.directory.iterdir()) and not native.launched


def test_prepared_receipt_is_not_execution_input(native, monkeypatch):
    receipt = handoff.prepare(native.signed(), **native.kwargs)
    sender, receiver = socket.socketpair()
    monkeypatch.setattr(channel, '_peer_uid', lambda _: native.pin.uid)
    with sender, receiver:
        sender.sendall(json.dumps(receipt).encode())
        sender.shutdown(socket.SHUT_WR)
        with pytest.raises(IdentityError, match='invalid signed recruitment envelope'):
            channel.launch_connected(receiver, args=native.args, **native.kwargs)
    assert not native.launched
    with rs.Store(native.pin) as store:
        assert store.db.execute('SELECT state FROM operations').fetchall() == [('prepared',)]


def test_lost_launch_reply_retains_live_attempt_and_replay_refuses(native, monkeypatch):
    monkeypatch.setattr(channel, '_peer_uid', lambda _: native.pin.uid)
    sender, receiver = socket.socketpair()
    sender.sendall(json.dumps(native.signed()).encode())
    sender.close()
    with receiver, pytest.raises(transport.DeliveryUnknown, match='retain durable state'):
        channel.launch_connected(receiver, args=native.args, **native.kwargs)
    assert len(native.launched) == 1
    with rs.Store(native.pin) as store:
        assert store.db.execute('SELECT state FROM operations').fetchall() == [('launched',)]
    with pytest.raises(IdentityError, match='replay'):
        exchange(native, monkeypatch)
    assert len(native.launched) == 1


def test_late_native_launch_retains_attempt_after_response_budget(native, monkeypatch):
    original = cli._launch

    def slow(*args, **kwargs):
        result = original(*args, **kwargs)
        time.sleep(0.08)
        return result

    monkeypatch.setattr(cli, '_launch', slow)
    with pytest.raises(transport.DeliveryUnknown, match='retain durable state'):
        exchange(native, monkeypatch, timeout=0.04)
    assert len(native.launched) == 1
    with rs.Store(native.pin) as store:
        assert store.db.execute('SELECT state FROM operations').fetchall() == [('launched',)]
