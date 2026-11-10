"""Passive receipts from the scheduled executor; never requests a cycle.

A MET receipt wakes the owner to check before/after acceptance. It does not
close the item or establish that context was saved or reduced.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

PREFIX = 'ST_NATURAL_IDLE_CYCLE '
PRODUCER = 'st-tend-auto-context/v1'
UNIT = 'st-tend.service'
MAX_ROWS = 100
MAX_BYTES = 1024 * 1024


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def receipt(request, agent, reading, result):
    """Only the existing successful auto-context path may emit this receipt."""
    from . import triage
    if (result != 0 or request.get('auto') is not True
            or request.get('runtime_update') or reading is None
            or reading.state not in (triage.IDLE, triage.SATURATED)
            or not _number(reading.depth_k)
            or reading.depth_k < triage.CYCLE_THRESHOLD_K
            or not _number(request.get('requested_at'))
            or not isinstance(request.get('checkpoint_bead'), str)
            or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}', request['checkpoint_bead'])
            or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', agent)):
        return None
    return PREFIX + json.dumps({
        'schema': 1, 'producer': PRODUCER, 'agent': agent,
        'requested_at': request['requested_at'],
        'context_before_k': reading.depth_k,
        'checkpoint_item': request['checkpoint_bead'],
        'result': 'cycle-returned-ok', 'origin': 'tend-auto-context',
    }, sort_keys=True, allow_nan=False)


def emit(request, agent, reading, result):
    import sys
    message = receipt(request, agent, reading, result)
    if message is not None:
        print(message, file=sys.stderr, flush=True)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate receipt field')
        result[key] = value
    return result


def decide(raw, binding, now, *, uid, boot):
    from .resume_events import Verdict
    try:
        if len(raw) > MAX_BYTES:
            raise ValueError('journal evidence exceeds byte bound')
        rows = raw.splitlines()
        if len(rows) > MAX_ROWS:
            raise ValueError('journal evidence reaches row bound')
        found = []
        for line in rows:
            row = json.loads(line, object_pairs_hook=_unique)
            if (row['_SYSTEMD_USER_UNIT'] != UNIT or row['_UID'] != str(uid)
                    or row['_BOOT_ID'] != boot
                    or not re.fullmatch(r'[0-9a-f]{32}', row['_SYSTEMD_INVOCATION_ID'])):
                raise ValueError('journal receipt has foreign or missing native identity')
            at = datetime.fromtimestamp(int(row['__REALTIME_TIMESTAMP']) / 1e6, timezone.utc)
            if not binding.not_before <= at <= now or now - at > timedelta(days=14):
                raise ValueError('journal receipt outside source binding interval')
            message = row['MESSAGE']
            if not message.startswith(PREFIX):
                raise ValueError('unexpected journal message')
            data = json.loads(message[len(PREFIX):], object_pairs_hook=_unique)
            if (type(data['schema']) is not int or data['schema'] != 1
                    or data['producer'] != PRODUCER
                    or data['origin'] != 'tend-auto-context'
                    or data['result'] != 'cycle-returned-ok'
                    or not _number(data['requested_at'])
                    or not _number(data['context_before_k'])
                    or not isinstance(data['checkpoint_item'], str)
                    or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}', data['checkpoint_item'])
                    or not isinstance(data['agent'], str)
                    or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', data['agent'])):
                raise ValueError('invalid automatic cycle receipt')
            from .triage import CYCLE_THRESHOLD_K
            requested = datetime.fromtimestamp(data['requested_at'], timezone.utc)
            if (data['context_before_k'] < CYCLE_THRESHOLD_K or requested > at
                    or at - requested > timedelta(days=14)):
                raise ValueError('receipt does not prove a bounded deep-context request')
            cursor = row['__CURSOR']
            if not isinstance(cursor, str) or not 1 <= len(cursor) <= 1024:
                raise ValueError('missing native journal cursor')
            found.append(cursor)
        digest = hashlib.sha256(raw).hexdigest()
        if found:
            return Verdict('MET', 'scheduled automatic idle-cycle receipt; owner acceptance still owed',
                           digest, tuple(found))
        return Verdict('UNKNOWN', 'no qualifying receipt in retained current-boot journal', digest)
    except (KeyError, TypeError, AttributeError, ValueError, OverflowError, OSError, RecursionError):
        return Verdict('UNKNOWN', 'invalid or incomplete native idle-cycle evidence')


def evaluate(binding, now):
    from .resume_events import Verdict
    try:
        if (binding.producer != PRODUCER or binding.unit != UNIT
                or binding.host != 'local-native-journal'
                or binding.generation != 'current-boot'
                or binding.window != 'post-registration'
                or now < binding.not_before):
            raise ValueError('source binding identity mismatch')
        # Fixed native source, never an item-provided query, path or command.
        # Read at most 101 messages: the extra row detects incomplete coverage.
        command = ['journalctl', '--user', '--unit', UNIT, '--boot=0',
                   '--since', binding.not_before.isoformat(), '--until', now.isoformat(),
                   '--grep', '^' + PREFIX, '--output=json', '--no-pager', '-n', str(MAX_ROWS + 1),
                   '--output-fields=MESSAGE,_SYSTEMD_USER_UNIT,_UID,_BOOT_ID,_SYSTEMD_INVOCATION_ID,__REALTIME_TIMESTAMP,__CURSOR']
        # Bound output while reading, rather than buffering arbitrary journal data.
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as proc:
            try:
                import selectors
                import time
                raw = bytearray()
                deadline = time.monotonic() + 5
                with selectors.DefaultSelector() as selector:
                    selector.register(proc.stdout, selectors.EVENT_READ)
                    while True:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0 or not selector.select(remaining):
                            raise ValueError('native journal read timed out')
                        chunk = os.read(proc.stdout.fileno(), min(65536, MAX_BYTES + 1 - len(raw)))
                        if not chunk:
                            break
                        raw.extend(chunk)
                        if len(raw) > MAX_BYTES:
                            raise ValueError('native journal output exceeds bound')
                if proc.wait(timeout=max(.001, deadline - time.monotonic())) != 0:
                    raise ValueError('native journal read failed')
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
        boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip().replace('-', '')
        if not re.fullmatch(r'[0-9a-f]{32}', boot):
            raise ValueError('native boot identity unavailable')
        return decide(bytes(raw), binding, now, uid=os.getuid(), boot=boot)
    except (OSError, ValueError, subprocess.SubprocessError):
        return Verdict('UNKNOWN', 'native scheduled idle-cycle journal unavailable or incomplete')
