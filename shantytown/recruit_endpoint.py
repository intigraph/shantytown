"""Default-OFF client for an operator-pinned controller Unix endpoint.

No caller chooses an address/UID, installs a socket, signs a request or launches
anything. The existing controller must still verify the signature, native
custody and durable nonce. A response remains data, never launch authority.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
import socket
import stat
import time

from .actor_identity import IdentityError
from . import recruit_request, recruit_transport
from .job_launch import protected

POLICY_PATH = Path('/etc/shantytown/recruit-endpoint.json')


def _descriptor(pin):
    data = recruit_request._protected_json(POLICY_PATH)
    if (not isinstance(data, dict)
            or set(data) != {'version', 'host', 'root', 'socket', 'socket_gid', 'controller_uid'}
            or type(data['version']) is not int or data['version'] != 1
            or data['host'] != pin.host or data['root'] != pin.root
            or type(data['controller_uid']) is not int or data['controller_uid'] < 0
            or data['controller_uid'] == pin.uid
            or type(data['socket_gid']) is not int or data['socket_gid'] < 0
            or not isinstance(data['socket'], str)):
        raise IdentityError('controller endpoint policy refused')
    path = Path(data['socket'])
    if (not path.is_absolute() or str(path) != data['socket']
            or '..' in path.parts or '\x00' in data['socket']
            or len(os.fsencode(path)) > 100):
        raise IdentityError('controller endpoint path refused')
    return data


def _socket_identity(endpoint):
    path = Path(endpoint['socket'])
    # The leaf is a group-writable socket, not a protected regular capability
    # file. Only its immutable root-owned parent chain uses that file validator.
    protected(path.parent, directory=True)
    meta = path.lstat()
    if (not stat.S_ISSOCK(meta.st_mode) or meta.st_uid != 0
            or meta.st_gid != endpoint['socket_gid']
            or stat.S_IMODE(meta.st_mode) != 0o660):
        raise IdentityError('controller endpoint socket refused')
    return meta.st_dev, meta.st_ino, meta.st_uid, meta.st_gid, meta.st_mode


def exchange(envelope, *, policy, timeout=5):
    """Connect once to the protected endpoint, then use the bounded transport.

    The activation gate precedes policy/socket access. All elapsed connection
    and validation time consumes the same five-second exchange budget. Pre-send
    refusal sends nothing; after entering transport, uncertainty keeps its
    existing no-retry meaning. The caller must retain its nonce/attempt record.
    """
    if getattr(policy, 'recruitment_launch_ready', False) is not True:
        raise IdentityError('controller recruitment activation is gated')
    if (type(timeout) not in (int, float) or not math.isfinite(timeout)
            or not 0 < timeout <= 5 or not hasattr(socket, 'SO_PEERCRED')):
        raise IdentityError('controller endpoint budget or platform refused')
    # Canonicalize before any callbacks so caller mutation cannot change which
    # identity is checked or which exact signed bytes are eventually sent.
    deadline = time.monotonic() + timeout
    from .recruit_controller import parse
    frozen = parse(recruit_transport._wire(envelope))
    channel = None
    try:
        pin = recruit_request.load_controller_binding()
        body = frozen['body']
        if (os.geteuid() != pin.uid or body['principal'] != pin.principal
                or type(body['uid']) is not int or body['uid'] != pin.uid or body['host'] != pin.host
                or body['repo'] not in pin.repos or not pin.root):
            raise IdentityError('controller endpoint caller differs from protected binding')
        endpoint = _descriptor(pin)
        identity = _socket_identity(endpoint)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise IdentityError('controller endpoint expired before connect')
        channel = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        channel.settimeout(remaining)
        channel.connect(endpoint['socket'])
        if (recruit_request.load_controller_binding() != pin
                or _descriptor(pin) != endpoint
                or _socket_identity(endpoint) != identity):
            raise IdentityError('controller endpoint changed before send')
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise IdentityError('controller endpoint expired before send')
        return recruit_transport.exchange(channel, frozen,
            peer_uid=endpoint['controller_uid'], timeout=remaining)
    except OSError:
        # Addresses, root configuration and arbitrary peer errors are not
        # diagnostic output. No bytes have been sent until transport takes over.
        raise IdentityError('controller endpoint unavailable before send') from None
    finally:
        if channel is not None:
            channel.close()
