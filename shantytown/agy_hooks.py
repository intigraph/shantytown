"""Translate native agy lifecycle payloads to the existing st hook contract."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time

from .agy import canonical, private_write, projected_hooks, receipt_path, native_process

TOOLS = {'run_command': 'Bash', 'write_file': 'Write', 'view_file': 'Read', 'write_to_file': 'Write',
         'replace_file_content': 'Edit', 'multi_replace_file_content': 'MultiEdit'}


def translated(event, native):
    tool = native.get('toolCall') or {}
    name, args = tool.get('name', ''), tool.get('args') or {}
    if event == 'PreToolUse' and name not in TOOLS and name != 'call_mcp_tool':
        raise ValueError('agy tool vocabulary is unqualified')
    if not isinstance(args, dict):
        raise ValueError('invalid native tool arguments')
    value = dict(args)
    if name == 'run_command':
        value = {'command': args.get('CommandLine'), 'cwd': args.get('Cwd')}
    elif name == 'write_file':
        value = {'file_path': args.get('Path'), 'content': args.get('Content')}
    elif name in ('write_to_file', 'replace_file_content', 'multi_replace_file_content'):
        value['file_path'] = args.get('TargetFile')
        value['content'] = args.get('CodeContent')
        value['old_string'] = args.get('TargetContent')
        value['new_string'] = args.get('ReplacementContent')
        if name == 'multi_replace_file_content':
            value['edits'] = [{'old_string': x.get('TargetContent'),
                               'new_string': x.get('ReplacementContent')}
                              for x in args.get('ReplacementChunks', [])]
    elif name == 'call_mcp_tool':
        server, method = args.get('ServerName'), args.get('ToolName')
        paths = native.get('workspacePaths') or []
        if (not isinstance(server, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', server)
                or not isinstance(method, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', method)
                or not isinstance(args.get('Arguments'), dict) or not paths):
            raise ValueError('agy MCP tool identity mapping is unqualified')
        kit = json.loads((Path(paths[0]) / '.agents/mcp_config.json').read_text())
        if server not in kit.get('mcpServers', {}):
            raise ValueError('agy MCP server is absent from the workspace kit')
        name = 'mcp__' + server + '__' + method
        value = args['Arguments']
    paths = native.get('workspacePaths') or []
    return {'hook_event_name': event, 'session_id': native.get('conversationId'),
            'transcript_path': native.get('transcriptPath'),
            'cwd': paths[0] if paths else None,
            'tool_name': TOOLS.get(name, name), 'tool_input': value,
            'tool_response': {'error': native.get('error', '')},
            'prompt': native.get('lastUserInput', ''), 'stop_hook_active': False}


def execute(command, payload, timeout, env):
    """Bound each native hook child and its descendants; never inherit a model ID."""
    import signal
    child = subprocess.Popen(['/bin/sh', '-c', command], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             env=env, start_new_session=True, text=True)
    try:
        try:
            stdout, stderr = child.communicate(json.dumps(payload), timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.communicate(timeout=10)
            raise ValueError('st agy hook timed out') from None
    finally:
        if child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait(timeout=10)
    if len(stdout) > 1024 * 1024:
        raise ValueError('st agy hook output exceeds limit')
    return child.returncode, stdout, stderr[:65536]


def dispatch(event, native, settings_path, *, runner=execute):
    text = Path(settings_path).read_text()
    data = canonical(text)
    if data is None:
        raise ValueError('agy canonical hook settings are unreadable')
    equivalent = 'UserPromptSubmit' if event == 'PreInvocation' else event
    # Prompt hooks fire once per user turn, not on every tool-loop invocation.
    if event == 'PreInvocation' and native.get('invocationNum') != 0:
        return {}
    normal_stop = (native.get('fullyIdle') is True
                   and native.get('terminationReason') == 'NO_TOOL_CALL')
    payload = translated(equivalent, native)
    env = dict(os.environ)
    for key in ('QUIPU_AGENT', 'QUIPU_SESSION', 'QUIPU_MODEL', 'QUIPU_HARNESS',
                'CLAUDECODE', 'CLAUDE_CODE_SESSION_ID', 'CODEX_HOME',
                'CODEX_THREAD_ID', 'CODEX_SESSION_ID'):
        env.pop(key, None)
    env.update(QUIPU_HARNESS='agy', QUIPU_HOST=socket.gethostname())
    for key, value in (('QUIPU_AGENT', env.get('SHANTY_AGENT')),
                       ('QUIPU_SESSION', native.get('conversationId')),
                       ('QUIPU_MODEL', native.get('modelName'))):
        if isinstance(value, str) and value:
            env[key] = value
    if event == 'SessionStart' and env.get('SHANTY_ROOT') and env.get('SHANTY_AGENT'):
        paths = native.get('workspacePaths') or []
        if not paths:
            raise ValueError('native agy workspace is absent')
        ws = Path(paths[0]).resolve()
        hooks = json.loads((ws / '.agents/hooks.json').read_text())
        if hooks.get('shantytown') != projected_hooks(settings_path):
            raise ValueError('native agy hooks do not match the launch projection')
        receipt = {k: native.get(k) for k in ('conversationId', 'workspacePaths', 'modelName', 'transcriptPath')}
        pid, identity = native_process()
        if not pid or not identity:
            raise ValueError('native agy process ancestry unproved')
        receipt.update(pid=pid, process_identity=identity, at=time.time(), settings=str(Path(settings_path).resolve()),
                       settings_sha256=hashlib.sha256(text.encode()).hexdigest(),
                       hooks_sha256=hashlib.sha256((ws / '.agents/hooks.json').read_bytes()).hexdigest())
        path = receipt_path(env['SHANTY_ROOT'], env['SHANTY_AGENT'])
        path.parent.mkdir(parents=True, exist_ok=True)
        private_write(path, json.dumps(receipt) + '\n')
    notes, reasons = [], []
    for group in data['hooks'].get(equivalent, []):
        matcher = group.get('matcher')
        if matcher and not re.search(matcher, payload['tool_name']):
            continue
        for hook in group.get('hooks', []):
            code, stdout, stderr = runner(hook['command'], payload,
                                         min(float(hook.get('timeout', 30)), 45), env)
            try:
                answer = json.loads(stdout) if stdout.strip() else {}
            except ValueError:
                answer = {}
                if event == 'SessionStart' and stdout.strip():
                    notes.append(stdout.strip())
            specific = answer.get('hookSpecificOutput') or {}
            denied = code == 2 or answer.get('decision') == 'block' or specific.get('permissionDecision') == 'deny'
            if event == 'PreToolUse' and (denied or code != 0):
                return {'decision': 'deny', 'reason': answer.get('reason') or specific.get('permissionDecisionReason') or stderr or 'st hook refused'}
            if denied:
                reasons.append(answer.get('reason') or stderr or 'st hook requests continuation')
            note = specific.get('additionalContext') or answer.get('systemMessage')
            if isinstance(note, str) and note:
                notes.append(note)
    if event == 'PreToolUse':
        return {'decision': 'allow'}
    if event == 'Stop':
        return ({'decision': 'continue', 'reason': '\n'.join(reasons + notes)}
                if normal_stop and reasons else {})
    if event in ('SessionStart', 'PreInvocation'):
        return {'injectSteps': [{'systemMessage': {'systemMessage': x}} for x in notes + reasons]}
    return {}


def _cancel(signum, frame):
    raise InterruptedError('st agy hook cancelled')


def main(argv=None):
    import signal
    signal.signal(signal.SIGTERM, _cancel)
    parser = argparse.ArgumentParser()
    parser.add_argument('--settings', required=True)
    parser.add_argument('--event', required=True,
                        choices=['SessionStart', 'PreInvocation', 'PreToolUse', 'PostToolUse', 'Stop'])
    args = parser.parse_args(argv)
    try:
        native = json.loads(sys.stdin.read(1024 * 1024))
        answer = dispatch(args.event, native, args.settings)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        # Never let an adapter error become a tool authorization.
        answer = {'decision': 'deny', 'reason': 'st agy hook could not verify tool'} if args.event == 'PreToolUse' else {}
        print(f'st agy hook: {type(exc).__name__}', file=sys.stderr)
        print(json.dumps(answer))
        return 1
    print(json.dumps(answer))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
