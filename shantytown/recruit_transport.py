"""One bounded exchange on a controller-owned connected Unix channel.

This module neither selects/connects an endpoint nor starts a listener. The
trusted caller must supply the configured controller UID and connected socket.
Peer credentials authenticate that channel, not its response as launch authority.
The receiver must still verify the signed request through recruit_controller.
No existing recruiter/launcher path calls this module; activation is separate.
"""
from __future__ import annotations

import json
import math
import re
import select
import socket
import struct
import time

from .actor_identity import IdentityError
from . import recruit_controller, recruit_request


class DeliveryUnknown(IdentityError):
    """A send may have reached the controller; never retry it automatically."""


def _wire(envelope):
    if (not isinstance(envelope, dict) or set(envelope) != {'body', 'signature'}
            or not isinstance(envelope['signature'], str)
            or not re.fullmatch('[0-9a-f]{128}', envelope['signature'])):
        raise IdentityError('transport envelope refused')
    recruit_request.message(envelope['body'])
    if (envelope['body']['job'] != 'review'
            or envelope['body']['verb'] not in ('launch', 'stop')):
        raise IdentityError('transport accepts review verbs only')
    raw = json.dumps(envelope, sort_keys=True, separators=(',', ':'),
                     ensure_ascii=True, allow_nan=False).encode('ascii')
    if len(raw) > recruit_controller.MAX_BYTES:
        raise IdentityError('transport request exceeds bound')
    return raw


def exchange(channel, envelope, *, peer_uid, timeout=5):
    """Send once, half-close, and read one EOF-delimited bounded JSON response.

    Pre-send failures refuse locally. Any failure after entering send is UNKNOWN,
    including timeout, malformed/oversized output and a lost response. A caller
    must retain its original nonce/attempt record and reconcile rather than send
    again. No response returned here proves admission, preparation or execution.
    The caller owns closing the socket; this consumes its write half.
    """
    raw = _wire(envelope)
    if (type(peer_uid) is not int or peer_uid < 0
            or type(timeout) not in (int, float) or not math.isfinite(timeout)
            or not 0 < timeout <= 5
            or not isinstance(channel, socket.socket)
            or channel.family != socket.AF_UNIX
            or channel.type & 0xf != socket.SOCK_STREAM
            or not hasattr(socket, 'SO_PEERCRED') or not hasattr(socket, 'MSG_DONTWAIT')):
        raise IdentityError('transport channel or budget refused')
    try:
        _, uid, _ = struct.unpack('3i', channel.getsockopt(
            socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))
        if uid != peer_uid:
            raise IdentityError('controller channel peer UID mismatch')
        channel.getpeername()
    except OSError:
        raise IdentityError('controller channel identity unavailable') from None
    deadline = time.monotonic() + timeout

    def ready(write=False):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        read, writable, _ = select.select(
            [] if write else [channel], [channel] if write else [], [], remaining)
        if not (writable if write else read):
            raise TimeoutError

    try:
        sent = 0
        while sent < len(raw):
            ready(write=True)
            try:
                count = channel.send(raw[sent:], socket.MSG_DONTWAIT)
            except BlockingIOError:
                continue
            if count <= 0:
                raise OSError
            sent += count
        channel.shutdown(socket.SHUT_WR)
        output = bytearray()
        while True:
            ready()
            try:
                chunk = channel.recv(min(4096, recruit_controller.MAX_BYTES + 1 - len(output)),
                                     socket.MSG_DONTWAIT)
            except BlockingIOError:
                continue
            if not chunk:
                return recruit_controller.parse(bytes(output))
            output.extend(chunk)
            if len(output) > recruit_controller.MAX_BYTES:
                raise ValueError
    except Exception:
        # Remote output, key material and arbitrary exception strings are never
        # diagnostic text, and no exception makes a possibly consumed nonce free.
        raise DeliveryUnknown('controller delivery uncertain; preserve attempt and nonce') from None
