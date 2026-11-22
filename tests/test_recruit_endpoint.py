"""Private Unix socket controls; root enrollment and protected metadata synthetic."""
from dataclasses import replace
import json
import os
from pathlib import Path
import socket
import stat
import tempfile
import threading
from types import SimpleNamespace

import pytest

from shantytown import recruit_endpoint as endpoint, recruit_request as rr
from shantytown.actor_identity import IdentityError
from test_recruitment_request import context, signed, native  # noqa: F401

pytestmark = pytest.mark.skipif(not hasattr(socket, 'SO_PEERCRED'), reason='Linux peer credentials')
READY = SimpleNamespace(recruitment_launch_ready=True)


@pytest.fixture
def enrolled(context, monkeypatch):
    key, pin, body, _ = context
    pin = replace(pin, root='/operator/deployment')
    monkeypatch.setattr(rr, 'load_controller_binding', lambda: pin)
    monkeypatch.setattr(os, 'geteuid', lambda: pin.uid)
    monkeypatch.setattr(endpoint, '_socket_identity', lambda _: (1, 2, 0, 3, 0o140660))
    return key, pin, body


def peer(enrolled, monkeypatch, run, responder):
    key, pin, body = enrolled
    seen = []
    with tempfile.TemporaryDirectory(prefix='re-') as tmp:
        path = str(Path(tmp) / 's')
        policy = dict(version=1, host=pin.host, root=pin.root, socket=path,
                      socket_gid=3, controller_uid=os.getuid())
        monkeypatch.setattr(rr, '_protected_json', lambda _: dict(policy))
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(path)
            server.listen(1)
            server.settimeout(1)
            def serve():
                try:
                    client, _ = server.accept()
                    with client:
                        client.settimeout(1)
                        raw = bytearray()
                        while chunk := client.recv(4096):
                            raw.extend(chunk)
                        seen.append(bytes(raw))
                        responder(client, bytes(raw))
                except (TimeoutError, BrokenPipeError, ConnectionResetError):
                    pass
            worker = threading.Thread(target=serve)
            worker.start()
            try:
                return run(signed(key, body), policy), seen
            finally:
                worker.join(2)
                assert not worker.is_alive()


def test_actual_channel_preserves_signature_and_existing_verifier(enrolled, monkeypatch, tmp_path):
    key, pin, body = enrolled
    def controller(channel, raw):
        with_ledger = rr.Ledger(tmp_path / 'verified.sqlite')
        try:
            assert rr.qualify(json.loads(raw), binding=pin, now=110,
                              ledger=with_ledger, native_binding=native) == body
        finally:
            with_ledger.close()
        channel.sendall(b'{"state":"prepared","live":false}')
    result, seen = peer(enrolled, monkeypatch,
        lambda envelope, _: endpoint.exchange(envelope, policy=READY), controller)
    assert result == {'state': 'prepared', 'live': False}
    assert len(seen) == 1 and json.loads(seen[0]) == signed(key, body)


def test_default_gate_precedes_binding_or_socket_access(monkeypatch):
    def forbidden():
        pytest.fail('binding accessed while activation gated')
    monkeypatch.setattr(rr, 'load_controller_binding', forbidden)
    with pytest.raises(IdentityError, match='activation is gated'):
        endpoint.exchange(None, policy=SimpleNamespace())


@pytest.mark.parametrize('change', [dict(version=True), dict(extra='x'),
    dict(host='another-host'), dict(root='/another-root'), dict(controller_uid=True),
    dict(controller_uid=10001), dict(socket_gid=-1), dict(socket='relative'),
    dict(socket='/tmp/../elsewhere'), dict(socket='/tmp//elsewhere'),
    dict(socket='/tmp/' + 's' * 101)])
def test_bad_root_descriptor_refuses_before_socket(enrolled, monkeypatch, change):
    key, pin, body = enrolled
    descriptor = dict(version=1, host=pin.host, root=pin.root, socket='/controller/s',
                      socket_gid=3, controller_uid=os.getuid()) | change
    monkeypatch.setattr(rr, '_protected_json', lambda _: descriptor)
    monkeypatch.setattr(endpoint, '_socket_identity', lambda _: pytest.fail('socket touched'))
    with pytest.raises(IdentityError):
        endpoint.exchange(signed(key, body), policy=READY)


@pytest.mark.parametrize('changes', [dict(st_uid=1), dict(st_gid=4),
    dict(st_mode=stat.S_IFLNK | 0o660), dict(st_mode=stat.S_IFREG | 0o660),
    dict(st_mode=stat.S_IFSOCK | 0o666), dict(st_mode=stat.S_IFSOCK | 0o600)])
def test_socket_kind_owner_group_and_mode_are_strict(monkeypatch, changes):
    meta = SimpleNamespace(**(dict(st_uid=0, st_gid=3, st_mode=stat.S_IFSOCK | 0o660,
                                  st_dev=1, st_ino=2) | changes))
    leaf = SimpleNamespace(parent='/protected-parent', lstat=lambda: meta)
    monkeypatch.setattr(endpoint, 'Path', lambda _: leaf)
    parents = []
    monkeypatch.setattr(endpoint, 'protected', lambda path, **kw: parents.append((path, kw)))
    with pytest.raises(IdentityError, match='socket refused'):
        endpoint._socket_identity({'socket': '/protected-parent/s', 'socket_gid': 3})
    assert parents == [('/protected-parent', {'directory': True})]


def test_wrong_controller_peer_sends_no_bytes(enrolled, monkeypatch):
    def run(envelope, policy):
        policy['controller_uid'] = os.getuid() + 1
        with pytest.raises(IdentityError, match='peer UID mismatch'):
            endpoint.exchange(envelope, policy=READY)
    _, seen = peer(enrolled, monkeypatch, run, lambda *_: None)
    assert seen == [b'']


def test_binding_replacement_after_connect_sends_no_bytes(enrolled, monkeypatch):
    _, pin, _ = enrolled
    pins = iter([pin, replace(pin, public_key=b'x' * 32)])
    monkeypatch.setattr(rr, 'load_controller_binding', lambda: next(pins))
    def run(envelope, _):
        with pytest.raises(IdentityError, match='changed before send'):
            endpoint.exchange(envelope, policy=READY)
    _, seen = peer(enrolled, monkeypatch, run, lambda *_: None)
    assert seen == [b'']


def test_lost_response_keeps_existing_uncertain_delivery(enrolled, monkeypatch):
    def run(envelope, _):
        with pytest.raises(endpoint.recruit_transport.DeliveryUnknown):
            endpoint.exchange(envelope, policy=READY)
    _, seen = peer(enrolled, monkeypatch, run, lambda *_: None)
    assert len(seen) == 1 and seen[0]


@pytest.mark.parametrize('budget', [0, -1, True, float('nan'), float('inf'), 6])
def test_bad_budget_refuses_before_binding(monkeypatch, budget):
    monkeypatch.setattr(rr, 'load_controller_binding', lambda: pytest.fail('binding touched'))
    with pytest.raises(IdentityError, match='budget or platform'):
        endpoint.exchange(None, policy=READY, timeout=budget)


def test_foreign_caller_never_selects_endpoint(enrolled, monkeypatch):
    key, pin, body = enrolled
    monkeypatch.setattr(os, 'geteuid', lambda: pin.uid + 1)
    monkeypatch.setattr(rr, '_protected_json', lambda _: pytest.fail('endpoint touched'))
    with pytest.raises(IdentityError, match='caller differs'):
        endpoint.exchange(signed(key, body), policy=READY)


def test_descriptor_replacement_after_connect_sends_no_bytes(enrolled, monkeypatch):
    def run(envelope, policy):
        descriptors = iter([dict(policy), dict(policy, controller_uid=os.getuid() + 1)])
        monkeypatch.setattr(rr, '_protected_json', lambda _: next(descriptors))
        with pytest.raises(IdentityError, match='changed before send'):
            endpoint.exchange(envelope, policy=READY)
    _, seen = peer(enrolled, monkeypatch, run, lambda *_: None)
    assert seen == [b'']


def test_socket_replacement_after_connect_sends_no_bytes(enrolled, monkeypatch):
    identities = iter([(1, 2, 0, 3, 0o140660), (1, 99, 0, 3, 0o140660)])
    monkeypatch.setattr(endpoint, '_socket_identity', lambda _: next(identities))
    def run(envelope, _):
        with pytest.raises(IdentityError, match='changed before send'):
            endpoint.exchange(envelope, policy=READY)
    _, seen = peer(enrolled, monkeypatch, run, lambda *_: None)
    assert seen == [b'']


def test_connect_and_revalidation_share_exchange_deadline(enrolled, monkeypatch):
    ticks = iter([0.0, 0.01, 6.0])
    monkeypatch.setattr(endpoint.time, 'monotonic', lambda: next(ticks))
    def run(envelope, _):
        with pytest.raises(IdentityError, match='expired before send'):
            endpoint.exchange(envelope, policy=READY)
    _, seen = peer(enrolled, monkeypatch, run, lambda *_: None)
    assert seen == [b'']


def test_callback_cannot_mutate_the_signed_input_before_send(enrolled, monkeypatch):
    _, pin, _ = enrolled
    def run(envelope, policy):
        def descriptor(_):
            envelope['body']['repo'] = 'intigraph/tampered'
            return dict(policy)
        monkeypatch.setattr(rr, '_protected_json', descriptor)
        return endpoint.exchange(envelope, policy=READY)
    result, seen = peer(enrolled, monkeypatch, run,
        lambda channel, raw: channel.sendall(b'{"live":false}'))
    assert result == {'live': False}
    assert json.loads(seen[0])['body']['repo'] == pin.repos[0]
