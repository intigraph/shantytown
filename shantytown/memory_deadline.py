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
import threading
import time

from .memory_remote import Unproven, _json

_LIMIT = 4096
_FIELDS = ('root', 'agent', 'server', 'deployment', 'project', 'owner', 'directory',
           'outbox', 'harness', 'account', 'max_new', 'settings', 'generation', 'lifecycle_event')


def _supervise(command, payload, *, seconds=2.0, watch_parent=False, result_limit=_LIMIT):
    if (isinstance(seconds, bool) or not isinstance(seconds, (int, float))
            or not math.isfinite(seconds) or not 0 < seconds <= 2
            or len(payload) > 16384 or os.name != 'posix'):
        raise Unproven('memory worker budget or platform unsupported')
    deadline = time.monotonic() + seconds
    reader = writer = None
    try:
        if watch_parent:
            reader, writer = os.pipe()
            command = [*command, '--lifeline-fd', str(reader)]
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, start_new_session=True,
                                   pass_fds=() if reader is None else (reader,))
    except BaseException:
        if writer is not None:
            os.close(writer)
        raise
    finally:
        if reader is not None:
            os.close(reader)
    try:
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, seconds)
            output, _ = process.communicate(payload, timeout=remaining)
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(command, seconds)
        except subprocess.TimeoutExpired:
            raise Unproven('memory deadline exceeded; outcome unknown; retain outbox') from None
    finally:
        # Closing the exclusive pipe also covers unexpected caller exceptions.
        # On abrupt caller death the OS closes it; the worker observes EOF.
        if writer is not None:
            os.close(writer)
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                process.communicate(timeout=0.25)
            except subprocess.TimeoutExpired:
                raise Unproven('memory deadline cleanup unproven; retain outbox') from None
    if process.returncode != 0 or len(output) > result_limit:
        raise Unproven('memory worker result unknown; retain outbox')
    value = _json(output)
    if (not isinstance(value, dict) or set(value) != {'result'}
            or not isinstance(value['result'], dict)):
        raise Unproven('memory worker result unproven')
    return value['result']


def run_sync(args):
    """Bound one explicit sync; no command, credential, or body on argv."""
    return _run(args, 'sync', seconds=2.0, result_limit=_LIMIT)


def run_inspect(args):
    """Local metadata scan: no identity lookup, network, or source body output."""
    return _run(args, 'inspect', seconds=1.0, result_limit=32768)


def _run(args, action, *, seconds, result_limit):
    value = {name: getattr(args, name, None) for name in _FIELDS}
    value = {name: str(item) if isinstance(item, Path) else item
             for name, item in value.items()}
    payload = json.dumps(dict(action=action, arguments=value), separators=(',', ':')).encode()
    return _supervise([sys.executable, '-m', 'shantytown.memory_deadline'], payload,
                      seconds=seconds, watch_parent=True, result_limit=result_limit)


def _watch_parent(fd):
    """Only the supervisor holds the write end; never target an external PID."""
    if os.name != 'posix' or os.getpgrp() != os.getpid():
        raise Unproven('memory worker is not an isolated process group')
    os.fstat(fd)  # Refuse an invalid channel before doing any work.

    def watch():
        try:
            # No data is part of this protocol. EOF, error, or unexpected data
            # all mean supervision is lost, not permission to continue syncing.
            os.read(fd, 1)
        finally:
            os.killpg(os.getpid(), signal.SIGKILL)

    threading.Thread(target=watch, name='memory-parent-lifeline', daemon=True).start()


def _worker():
    # Save the private result pipe, then suppress incidental provider diagnostics.
    # Only the bounded metadata result can reach the caller, never exceptions.
    result_fd = os.dup(sys.stdout.fileno())
    with open(os.devnull, 'wb') as sink:
        os.dup2(sink.fileno(), 1)
        os.dup2(sink.fileno(), 2)
    try:
        if len(sys.argv) != 3 or sys.argv[1] != '--lifeline-fd':
            return 2
        _watch_parent(int(sys.argv[2]))
        raw = sys.stdin.buffer.read(16385)
        if len(raw) > 16384:
            return 2
        envelope = _json(raw)
        if (not isinstance(envelope, dict) or set(envelope) != {'action', 'arguments'}
                or envelope['action'] not in {'sync', 'inspect', 'lifecycle', 'prepare-native'}):
            return 2
        value = envelope['arguments']
        if not isinstance(value, dict) or set(value) != set(_FIELDS):
            return 2
        for name in ('root', 'directory', 'outbox', 'settings'):
            if value[name] is not None:
                value[name] = Path(value[name])
        from .memory_cli import execute
        result = execute(argparse.Namespace(memory_action=envelope['action'], **value))
        data = json.dumps({'result': result}, separators=(',', ':')).encode()
        limit = 32768 if envelope['action'] == 'inspect' else _LIMIT
        if len(data) > limit:
            return 2
        # The caller drains the pipe under its deadline; partial writes are not
        # success and metadata cannot exceed the action's fixed bound.
        with os.fdopen(os.dup(result_fd), 'wb') as stream:
            stream.write(data)
        return 0
    except Exception:
        return 2
    finally:
        os.close(result_fd)


if __name__ == '__main__':
    raise SystemExit(_worker())
