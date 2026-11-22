"""One protected inherited listener; no socket installation or runtime wiring."""
from __future__ import annotations

import math
import os
import select
import socket
import time

from .actor_identity import IdentityError
from . import recruit_channel, recruit_controller, recruit_endpoint, recruit_request


def launch_once(listener, *, args, timeout=5, **context):
    """Accept once, then enter the existing signed connected-channel launch path.

    A trusted installer must supply a nonblocking listener. This function never
    binds, unlinks, changes listener flags, retries or selects a caller's address.
    The caller owns the listener; this function closes only the accepted socket.
    Late/lost launch replies retain the existing durable uncertainty semantics.
    """
    recruit_controller.controller_authority(
        policy=context['policy'], actor=context['actor'], inside=context['inside'],
        role_of=context['role_of'])
    if getattr(context['policy'], 'recruitment_launch_ready', False) is not True:
        raise IdentityError('controller recruitment activation is gated')
    if (type(timeout) not in (int, float) or not math.isfinite(timeout)
            or not 0 < timeout <= 5):
        raise IdentityError('controller receiver budget refused')
    deadline = time.monotonic() + timeout
    channel = None
    try:
        pin = recruit_request.load_controller_binding()
        endpoint = recruit_endpoint._descriptor(pin)
        if os.geteuid() != endpoint['controller_uid']:
            raise IdentityError('controller receiver UID mismatch')
        if (not isinstance(listener, socket.socket) or listener.family != socket.AF_UNIX
                or listener.type & 0xf != socket.SOCK_STREAM or listener.gettimeout() != 0
                or not listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN)
                or listener.getsockname() != endpoint['socket']):
            raise IdentityError('controller inherited listener refused')
        identity = recruit_endpoint._socket_identity(endpoint)
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([listener], [], [], remaining)[0]:
            raise IdentityError('controller receiver expired before accept')
        # Nonblocking accept makes a competing acceptor a refusal, never an
        # unbounded wait or an implicit second request attempt.
        channel, _ = listener.accept()
        if (recruit_request.load_controller_binding() != pin
                or recruit_endpoint._descriptor(pin) != endpoint
                or recruit_endpoint._socket_identity(endpoint) != identity):
            raise IdentityError('controller receiver binding or endpoint changed')
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise IdentityError('controller receiver expired before handoff')
    except OSError:
        if channel is not None:
            channel.close()
        raise IdentityError('controller receiver unavailable before handoff') from None
    except BaseException:
        if channel is not None:
            channel.close()
        raise
    with channel:
        return recruit_channel.launch_connected(
            channel, args=args, timeout=remaining, **context)
