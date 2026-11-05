"""Original process hostname, distinct from a private UTS display hostname.

The normal launcher captures this before any namespace boundary. This is
attribution, never authentication, privilege or a configured fleet-host alias.
Unpinned invocations retain their original kernel-hostname behavior.
"""
import os
import re
import socket

ENV = "SHANTY_PHYSICAL_HOST"


def physical_hostname(*, env=None):
    env = os.environ if env is None else env
    if ENV not in env:
        return socket.gethostname()
    value = env[ENV]
    if (not isinstance(value, str) or len(value) > 253
            or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", value)):
        raise ValueError("invalid pinned physical hostname")
    # Preserve case and spelling: lifecycle producer hashes already depend on it.
    return value
