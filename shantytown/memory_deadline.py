"""One explicit sync in a bounded disposable process; no lifecycle activation.

Termination cannot retract a remote commit. The frozen intent and active batch
remain authoritative for later explicit receipt readback. No retry occurs here.
The deadline includes process startup, with at most 250ms for kill/reap cleanup;
uninterruptible OS work or scheduler starvation cannot be promised a hard bound.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from .memory_remote import Unproven, _json

_LIMIT = 4096
_FIELDS = ('root', 'agent', 'server', 'deployment', 'project', 'owner', 'directory',
           'outbox', 'harness', 'account', 'max_new')


def _supervise(command, payload, *, seconds=2.0):
    if (isinstance(seconds, bool) or not isinstance(seconds, (int, float))
            or not math.isfinite(seconds) or not 0 < seconds <= 2
            or len(payload) > 16384 or os.name != 'posix'):
        raise Unproven('memory worker budget or platform unsupported')
    deadline = time.monotonic() + seconds
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(command, seconds)
        output, _ = process.communicate(payload, timeout=remaining)
        if time.monotonic() >= deadline:
            raise subprocess.TimeoutExpired(command, seconds)
    except subprocess.TimeoutExpired:
        # Only this newly created one-shot process group is signalled. Never
        # target a crew session, provider, service, or external runtime PID.
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            process.communicate(timeout=0.25)
        except subprocess.TimeoutExpired:
            raise Unproven('memory deadline cleanup unproven; retain outbox') from None
        raise Unproven('memory deadline exceeded; outcome unknown; retain outbox') from None
    if process.returncode != 0 or len(output) > _LIMIT:
        raise Unproven('memory worker result unknown; retain outbox')
    value = _json(output)
    if (not isinstance(value, dict) or set(value) != {'result'}
            or not isinstance(value['result'], dict)):
        raise Unproven('memory worker result unproven')
    return value['result']


def run_sync(args):
    """Bound one explicit sync; no command, credential, or body on argv."""
    value = {name: getattr(args, name, None) for name in _FIELDS}
    value = {name: str(item) if isinstance(item, Path) else item
             for name, item in value.items()}
    payload = json.dumps(value, separators=(',', ':')).encode()
    return _supervise([sys.executable, '-m', 'shantytown.memory_deadline'], payload)


def _worker():
    # Save the private result pipe, then suppress incidental provider diagnostics.
    # Only the bounded metadata result can reach the caller, never exceptions.
    result_fd = os.dup(sys.stdout.fileno())
    with open(os.devnull, 'wb') as sink:
        os.dup2(sink.fileno(), 1)
        os.dup2(sink.fileno(), 2)
    try:
        raw = sys.stdin.buffer.read(16385)
        if len(raw) > 16384:
            return 2
        value = _json(raw)
        if not isinstance(value, dict) or set(value) != set(_FIELDS):
            return 2
        for name in ('root', 'directory', 'outbox'):
            if value[name] is not None:
                value[name] = Path(value[name])
        from .memory_cli import execute
        result = execute(argparse.Namespace(memory_action='sync', **value))
        data = json.dumps({'result': result}, separators=(',', ':')).encode()
        if len(data) > _LIMIT:
            return 2
        # Small metadata only, below PIPE_BUF; a failed write is UNKNOWN.
        if os.write(result_fd, data) != len(data):
            return 2
        return 0
    except Exception:
        return 2
    finally:
        os.close(result_fd)


if __name__ == '__main__':
    raise SystemExit(_worker())
