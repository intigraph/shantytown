"""Existing controller preparation over one already-connected local channel.

No listener, endpoint selector, configuration installer or launch callback.
This is deliberately a preparation adapter: its durable receipt never authorizes
later execution. Runtime wiring and activation remain separately gated.
"""
from __future__ import annotations

import json
import math
import select
import socket
import struct
import time

from .actor_identity import IdentityError
from . import recruit_controller, recruit_handoff, recruit_request
from .recruit_transport import DeliveryUnknown


def _peer_uid(channel):
    if (not isinstance(channel, socket.socket) or channel.family != socket.AF_UNIX
            or channel.type & 0xf != socket.SOCK_STREAM
            or not hasattr(socket, 'SO_PEERCRED') or not hasattr(socket, 'MSG_DONTWAIT')):
        raise IdentityError('controller requires a connected Unix stream')
    try:
        channel.getpeername()
        return struct.unpack('3i', channel.getsockopt(
            socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))[1]
    except OSError:
        raise IdentityError('recruiter channel identity unavailable') from None


def prepare_connected(channel, *, timeout=5, **context):
    """Authenticate the peer, consume one frame, then use existing preparation.

    Only the independently verified controller may enter. The expected sender
    UID comes from the protected binding, never an argument or envelope field.
    The I/O budget includes time spent in admission, but cannot cancel admission:
    if it finishes late, no response is sent and durable state is retained.
    Admission uses its existing adapter ceilings; no job can launch here.
    The caller owns closing the socket, including after any refusal.
    """
    recruit_controller.controller_authority(
        policy=context['policy'], actor=context['actor'], inside=context['inside'],
        role_of=context['role_of'])
    if (type(timeout) not in (int, float) or not math.isfinite(timeout)
            or not 0 < timeout <= 5):
        raise IdentityError('controller channel budget refused')
    pin = recruit_request.load_controller_binding()
    if _peer_uid(channel) != pin.uid:
        raise IdentityError('controller channel recruiter UID mismatch')
    deadline = time.monotonic() + timeout

    def ready(write=False):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        read, writable, _ = select.select(
            [] if write else [channel], [channel] if write else [], [], remaining)
        if not (writable if write else read):
            raise TimeoutError

    raw = bytearray()
    try:
        while True:
            ready()
            try:
                chunk = channel.recv(min(4096, recruit_controller.MAX_BYTES + 1 - len(raw)),
                                     socket.MSG_DONTWAIT)
            except BlockingIOError:
                continue
            if not chunk:
                break
            raw.extend(chunk)
            if len(raw) > recruit_controller.MAX_BYTES:
                raise ValueError
        envelope = recruit_controller.parse(bytes(raw))
    except Exception:
        raise IdentityError('controller channel frame refused') from None

    # Re-enter the existing protected authority/binding/store/planner path.
    # In particular, a changed binding after peer authentication must refuse.
    if recruit_request.load_controller_binding() != pin:
        raise IdentityError('controller binding changed during channel read')
    if time.monotonic() >= deadline:
        raise IdentityError('controller channel expired before preparation')
    receipt = recruit_handoff.prepare(envelope, **context)
    try:
        if (receipt.get('live') is not False or receipt.get('execution') != 'refused'
                or receipt.get('activation') != 'gated' or receipt.get('state') != 'prepared'):
            raise ValueError
        output = json.dumps(receipt, sort_keys=True, separators=(',', ':'),
                            allow_nan=False).encode('ascii')
        if len(output) > recruit_controller.MAX_BYTES:
            raise ValueError
        sent = 0
        while sent < len(output):
            ready(write=True)
            try:
                count = channel.send(output[sent:], socket.MSG_DONTWAIT)
            except BlockingIOError:
                continue
            if count <= 0:
                raise OSError
            sent += count
        channel.shutdown(socket.SHUT_WR)
    except Exception:
        raise DeliveryUnknown('prepared controller result uncertain; retain durable state') from None
    return receipt
