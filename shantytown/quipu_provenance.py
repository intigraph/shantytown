"""Declared request context; it never substitutes for authenticated identity."""
from __future__ import annotations

import os
import socket
from contextlib import contextmanager
from contextvars import ContextVar


_hook_session = ContextVar('quipu_hook_session', default=None)


@contextmanager
def hook_session(session):
    """Carry the native hook identity through synchronous publication only.

    Hooks receive their session in JSON even when the harness exports no session
    environment. Do not mutate process environment or retain a previous hook's ID.
    """
    value = session if isinstance(session, str) and session.strip() else None
    token = _hook_session.set(value)
    try:
        yield
    finally:
        _hook_session.reset(token)


def headers() -> dict[str, str]:
    """Derive each request from its actual environment, without inventing a session.

    Non-agent CLI invocations identify the producer, as the other stack writers
    do. An agent session with missing context stays partial so monitoring can
    still see the gap. Never borrow an inherited other harness's session ID.
    """
    def get(key):
        return os.environ.get(key) or None

    harness = get('QUIPU_HARNESS')
    if not harness:
        harness = 'claude' if get('CLAUDECODE') == '1' else 'codex' if get('CODEX_HOME') else 'cli'
    in_session = get('CLAUDECODE') == '1' or bool(get('CODEX_HOME'))
    session = _hook_session.get() or get('QUIPU_SESSION')
    if not session and harness == 'codex':
        session = get('CODEX_SESSION_ID') or get('CODEX_THREAD_ID')
    elif not session and harness == 'claude':
        session = get('CLAUDE_CODE_SESSION_ID')
    fields = {
        'Agent': get('QUIPU_AGENT') or (get('SHANTY_AGENT') if in_session else 'shantytown'),
        'Harness': harness,
        'Model': get('QUIPU_MODEL') or get('SHANTY_MODEL'),
        'Session': session,
        'Host': get('QUIPU_HOST') or socket.gethostname(),
    }
    result = {'X-Quipu-Client': 'shantytown'}
    for name, value in fields.items():
        if value:
            cleaned = ''.join(c for c in value if '\x20' <= c <= '\x7e').strip()[:128]
            if cleaned:
                result['X-Quipu-' + name] = cleaned
    return result
