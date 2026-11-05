"""Opt-in, bounded Stop reminder; observations are cues, never graph truth.

# arming: library OFF by default; enabled only through the existing Stop policy.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sys
from pathlib import Path
import re
import shlex
import stat

MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 20000
MARKER = re.compile(r'^(?:\[from stiwi\]\s*)?Stiwi\s+(?:ruling|decided)\s*:\s*(\S[^\n]{5,999})$', re.I)
SCOPE = re.compile(r'^[A-Za-z][A-Za-z0-9_:/#.?=-]{0,255}$')


def enabled(root):
    from .deployment import deployment_default
    return deployment_default(root, 'SHANTY_STOP_RULING_MEMORY') == '1'


def _records(payload):
    session, source = payload.get('session_id'), payload.get('transcript_path')
    if not isinstance(session, str) or not session or not isinstance(source, str):
        raise ValueError('missing session identity')
    fd = os.open(source, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('not a regular transcript')
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES or not data.endswith(b'\n'):
        raise ValueError('incomplete or over-cap transcript')
    lines = data.splitlines()
    if len(lines) > MAX_ROWS:
        raise ValueError('row cap')
    rows = [json.loads(line) for line in lines if line.strip()]
    if not rows or any(not isinstance(row, dict) for row in rows):
        raise ValueError('invalid transcript')
    codex = rows[0].get('type') == 'session_meta'
    if codex:
        meta = rows[0].get('payload', {})
        if (meta.get('id') or meta.get('session_id')) != session:
            raise ValueError('foreign session')
        for row in rows:
            if row.get('type') == 'session_meta':
                identity = row.get('payload', {})
                if (identity.get('id') or identity.get('session_id')) != session:
                    raise ValueError('mixed session')
    else:
        ids = {r['sessionId'] for r in rows if r.get('sessionId')}
        if ids != {session}:
            raise ValueError('unbound or mixed session')
    return rows, codex


def _text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return '\n'.join(b.get('text', '') for b in content
                         if isinstance(b, dict) and b.get('type') in ('text', 'input_text'))
    return ''


def _ruling(text):
    lines = text.strip().splitlines()
    match = MARKER.fullmatch(lines[0]) if lines else None
    if not match or match[1].rstrip().endswith('?'):
        return None
    fields = {}
    for line in lines[1:]:
        key, sep, value = line.partition(':')
        if sep and key.lower() in ('about', 'topic') and SCOPE.fullmatch(value.strip()):
            fields[key.lower()] = value.strip()
    return dict(chose=match[1], **fields)


def _write_call(name, args):
    if re.search(r'(?:^|__)(?:quipu_episode|quipu_knot|record_decision|record_directive)$', name):
        return 'mcp'
    if name not in ('Bash', 'exec_command', 'functions.exec_command'):
        return None
    if isinstance(args, str):
        args = json.loads(args)
    if not isinstance(args, dict):
        return None
    command = args.get('command', args.get('cmd', ''))
    words = shlex.split(command)
    # Only a direct CLI command, never a quoted example or composite shell/code.
    if any(c in command for c in ('\n', ';', '|', '&', '`', '$(')):
        return None
    if len(words) >= 3 and Path(words[0]).name in ('cy', 'camayoc') and words[1] == 'record':
        return 'cy'
    return None


def _success(output, kind):
    if isinstance(output, list):
        return any(_success(b.get('text'), kind) for b in output
                   if isinstance(b, dict) and b.get('type') == 'text')
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except ValueError:
            return False
    if not isinstance(output, dict):
        return False
    if (output.get('isError') not in (None, False) or output.get('error')
            or output.get('errors') or output.get('conforms') is False
            or str(output.get('status', '')).lower() in ('queued', 'refused', 'unknown', 'failed')
            or str(output.get('result', '')).lower() in ('blocked', 'refused', 'unknown', 'error', 'queued', 'dry-run')):
        return False
    if kind == 'cy':
        return (output.get('exit_code') == 0 and
                re.search(r'(?m)^(?:(?:recorded \w+|unchanged) https?://\S+|superseded https?://\S+ -> https?://\S+)$',
                          output.get('output', '')) is not None)
    if (output.get('status') in ('recorded', 'unchanged', 'superseded')
            and isinstance(output.get('iri'), str)
            and re.fullmatch(r'https?://[^\s]+', output['iri'])):
        return True
    if any(type(output.get(k)) is int and output[k] > 0 for k in ('tx', 'tx_id')):
        return True
    if isinstance(output.get('structuredContent'), dict):
        return _success(output['structuredContent'], kind)
    return any(_success(b.get('text'), kind) for b in output.get('content', [])
               if isinstance(b, dict) and b.get('type') == 'text')


def pending(payload):
    """Only explicit user markers and paired positive write receipts qualify.

    Any incomplete/unknown transcript returns via the caller's fail-open seam.
    A write before a new ruling does not discharge that ruling's reminder.
    """
    rows, codex = _records(payload)
    rulings, calls = {}, {}
    for row in rows:
        message = row.get('payload', {}) if codex else row.get('message', {})
        if codex and row.get('type') != 'response_item':
            continue
        if message.get('role') == 'user':
            ruling = _ruling(_text(message.get('content')))
            if ruling:
                key = hashlib.sha256(json.dumps(ruling, sort_keys=True).encode()).hexdigest()
                rulings[key] = ruling
        if codex:
            blocks = [message]
        else:
            blocks = message.get('content', [])
            if not isinstance(blocks, list):
                blocks = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            kind = block.get('type')
            if kind in ('tool_use', 'function_call') and (codex or message.get('role') == 'assistant'):
                call = block.get('id') or block.get('call_id')
                action = _write_call(block.get('name', ''), block.get('input', block.get('arguments', {})))
                if call and action:
                    calls[call] = (action, set(rulings))
            elif kind in ('tool_result', 'function_call_output'):
                call = block.get('tool_use_id') or block.get('call_id')
                if call in calls and not block.get('is_error'):
                    action, covered = calls.pop(call)
                    value = block.get('output', block.get('content'))
                    # Claude Bash emits text rather than the exec_command wrapper.
                    if action == 'cy' and kind == 'tool_result':
                        value = dict(exit_code=0, output=_text(value))
                    if _success(value, action):
                        for key in covered:
                            rulings.pop(key, None)
    return rulings


def command(ruling):
    words = ['cy', 'record', 'decision', '--chose', ruling['chose'], '--by', 'person-stiwi']
    result = shlex.join(words)
    for flag in ('about', 'topic'):
        value = ruling.get(flag)
        result += ' --' + flag + ' ' + (shlex.quote(value) if value else
                   '"${RULING_' + flag.upper() + ':?set an existing ' +
                   ('entity IRI' if flag == 'about' else 'registered memory topic') + '}"')
    return result


def check(root, me, payload):
    """Claim the state durably BEFORE emitting. A failed claim never blocks."""
    if not enabled(root):
        return None
    from .stop_policy import P0Ledger
    try:
        rulings = pending(payload)
        if not rulings:
            return None
        session = hashlib.sha256(payload['session_id'].encode()).hexdigest()
        state = hashlib.sha256(json.dumps(sorted(rulings)).encode()).hexdigest()
        ledger = P0Ledger(Path(root) / 'ruling-memory' / session)
        ledger._dir.mkdir(parents=True, exist_ok=True)
        with (ledger._dir / (me + '.lock')).open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if ledger.last(me) == state:
                return None
            ledger.record(me, state)
        commands = '\n'.join(command(r) for r in list(rulings.values())[:4])
        return ('Possible explicit Stiwi ruling; no confirmed subsequent Quipu write '
                'receipt in this bounded session transcript. Held once for this ruling state; '
                'the same state will not block again. Verify the attribution and scope, '
                'then record it with Camayoc (fill any required RULING_ABOUT/RULING_TOPIC '
                'variables from existing entities/topics):\n' + commands +
                '\nQueued, refused or unobserved writes are not confirmed records. '
                'This reminder does not write to Quipu or verify graph contents.')
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        print(f'ruling_memory: UNKNOWN ({type(exc).__name__}); allowing Stop', file=sys.stderr)
        return None
