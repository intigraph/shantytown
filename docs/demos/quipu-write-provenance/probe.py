"""Same helper call against a selected source; synthetic context, no network."""
import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, sys.argv[1])
from shantytown import quipu_auth

keys = ('QUIPU_AGENT', 'QUIPU_HARNESS', 'QUIPU_MODEL', 'QUIPU_SESSION', 'QUIPU_HOST',
        'SHANTY_AGENT', 'SHANTY_MODEL', 'CLAUDECODE', 'CLAUDE_CODE_SESSION_ID',
        'CODEX_HOME', 'CODEX_SESSION_ID', 'CODEX_THREAD_ID')
for key in keys:
    os.environ.pop(key, None)
fields = ('Agent', 'Harness', 'Model', 'Session', 'Host')
with patch.object(quipu_auth, 'token', return_value='fixture-only'), \
        patch.object(quipu_auth, 'status', return_value='ready'):
    os.environ.update(QUIPU_AGENT='fixture-agent', QUIPU_HARNESS='codex',
                      QUIPU_MODEL='fixture-model', QUIPU_SESSION='fixture-session',
                      QUIPU_HOST='fixture-host')
    headers = quipu_auth.write_headers('https://fixture.invalid')
    print(json.dumps({'fixture': 'complete context', 'headers': {
        field: headers.get('X-Quipu-' + field) for field in fields}}))
    os.environ.pop('QUIPU_AGENT')
    os.environ.pop('QUIPU_MODEL')
    os.environ.update(CODEX_HOME='/fixture/codex')
    headers = quipu_auth.write_headers('https://fixture.invalid')
    print(json.dumps({'fixture': 'incomplete agent context', 'headers': {
        field: headers.get('X-Quipu-' + field) for field in fields}}))
