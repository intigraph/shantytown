"""Real listener/signature/store/spawn; synthetic enrollment and job launcher."""
from dataclasses import replace
import json
import os
import socket
import threading
import tempfile

import pytest

from shantytown import recruit_channel, recruit_endpoint, recruit_receiver as receiver
from shantytown import recruit_transport
from shantytown.actor_identity import IdentityError
from test_recruit_launch import native, ctx, private_store  # noqa: F401

REAL_PEER_UID = recruit_channel._peer_uid


@pytest.fixture
def listening(native, monkeypatch):
    # Pytest's guarded HOME path can exceed the kernel's Unix address bound.
    directory = tempfile.TemporaryDirectory(prefix='st-rcv-', dir='/tmp')
    address = directory.name + '/controller.sock'
    descriptor = dict(version=1, host=native.pin.host, root=native.pin.root,
                      socket=address, socket_gid=os.getgid(), controller_uid=os.geteuid())
    monkeypatch.setattr(recruit_endpoint, '_descriptor', lambda _: dict(descriptor))
    # No root-owned socket or recruiter UID is enrolled by these tests.
    monkeypatch.setattr(recruit_endpoint, '_socket_identity', lambda _: ('synthetic-root-socket',))
    monkeypatch.setattr(recruit_channel, '_peer_uid', lambda _: native.pin.uid)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(address)
            listener.listen(1)
            listener.setblocking(False)
            yield listener, descriptor
    finally:
        directory.cleanup()


def request(native, listener, *, envelope=None, raw=False):
    outcomes = []
    def send():
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(listener.getsockname())
            try:
                signed = native.signed() if envelope is None else envelope
                if raw:
                    # Bypass the client's allowlist to exercise the controller.
                    client.sendall(json.dumps(signed).encode())
                    client.shutdown(socket.SHUT_WR)
                    outcomes.append(client.recv(8192))
                else:
                    outcomes.append(recruit_transport.exchange(client, signed, peer_uid=os.geteuid()))
            except Exception as error:
                outcomes.append(error)
    worker = threading.Thread(target=send)
    worker.start()
    try:
        result = receiver.launch_once(listener, args=native.args, timeout=1, **native.kwargs)
    finally:
        worker.join(2)
        assert not worker.is_alive()
    assert outcomes == [result]
    return result


def test_real_listener_signed_request_launches_once_and_keeps_listener(native, listening):
    listener, _ = listening
    assert request(native, listener)['state'] == 'launched'
    assert len(native.launched) == 1 and listener.fileno() >= 0
    assert listener.gettimeout() == 0
    with pytest.raises(IdentityError, match='replay'):
        request(native, listener)
    assert len(native.launched) == 1


def test_gate_precedes_listener_or_descriptor_access(native, monkeypatch):
    native.kwargs['policy'] = replace(native.kwargs['policy'], recruitment_launch_ready=False)
    def forbidden(_):
        pytest.fail('descriptor accessed before gate')
    monkeypatch.setattr(recruit_endpoint, '_descriptor', forbidden)
    with pytest.raises(IdentityError, match='activation is gated'):
        receiver.launch_once(None, args=native.args, **native.kwargs)
    assert not native.launched and not list(native.directory.iterdir())


@pytest.mark.parametrize('change', ['uid', 'address', 'blocking', 'not-listening'])
def test_wrong_listener_refuses_before_nonce(native, listening, change):
    listener, descriptor = listening
    if change == 'uid': descriptor['controller_uid'] += 1
    elif change == 'address': descriptor['socket'] += '-wrong'
    elif change == 'blocking': listener.setblocking(True)
    else:
        listener.close()
    with pytest.raises(IdentityError):
        receiver.launch_once(listener, args=native.args, timeout=.02, **native.kwargs)
    assert not native.launched and not list(native.directory.iterdir())


def test_no_connection_times_out_without_nonce(native, listening):
    listener, _ = listening
    with pytest.raises(IdentityError, match='expired before accept'):
        receiver.launch_once(listener, args=native.args, timeout=.01, **native.kwargs)
    assert not native.launched and not list(native.directory.iterdir())


def test_socket_replacement_after_accept_refuses_before_nonce(native, listening, monkeypatch):
    listener, _ = listening
    calls = iter([('before',), ('after',)])
    monkeypatch.setattr(recruit_endpoint, '_socket_identity', lambda _: next(calls))
    with pytest.raises(IdentityError, match='endpoint changed'):
        request(native, listener)
    assert not native.launched and not list(native.directory.iterdir())


def test_actual_wrong_peer_is_refused_before_nonce(native, listening, monkeypatch):
    listener, _ = listening
    monkeypatch.setattr(recruit_channel, '_peer_uid', REAL_PEER_UID)
    with pytest.raises(IdentityError, match='UID mismatch'):
        request(native, listener)
    assert not native.launched


def test_merge_request_never_launches(native, listening, monkeypatch):
    listener, _ = listening
    seen = []
    parse = recruit_channel.recruit_controller.parse
    def observe(raw):
        seen.append(json.loads(raw)['body']['job'])
        return parse(raw)
    monkeypatch.setattr(recruit_channel.recruit_controller, 'parse', observe)
    native.body['job'] = 'merge'
    with pytest.raises(IdentityError):
        request(native, listener, raw=True)
    assert seen == ['merge']
    assert not native.launched


@pytest.mark.parametrize('budget', [True, 0, -1, 5.01, float('nan'), float('inf'), '1'])
def test_invalid_budget_refuses_before_descriptor(native, monkeypatch, budget):
    monkeypatch.setattr(recruit_endpoint, '_descriptor', lambda _: pytest.fail('policy touched'))
    with pytest.raises(IdentityError, match='budget refused'):
        receiver.launch_once(None, args=native.args, timeout=budget, **native.kwargs)
    assert not native.launched


def test_binding_change_after_accept_refuses(native, listening, monkeypatch):
    listener, _ = listening
    pins = iter([native.pin, replace(native.pin, uid=native.pin.uid + 1)])
    monkeypatch.setattr(receiver.recruit_request, 'load_controller_binding', lambda: next(pins))
    with pytest.raises(IdentityError, match='binding or endpoint changed'):
        request(native, listener)
    assert not native.launched and not list(native.directory.iterdir())


def test_lost_response_keeps_durable_launch_without_retry(native, listening):
    listener, _ = listening
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(listener.getsockname())
        client.sendall(json.dumps(native.signed()).encode())
    with pytest.raises(recruit_transport.DeliveryUnknown, match='retain durable state'):
        receiver.launch_once(listener, args=native.args, timeout=1, **native.kwargs)
    assert len(native.launched) == 1
    with pytest.raises(IdentityError, match='replay'):
        request(native, listener)
    assert len(native.launched) == 1
