"""Antigravity 1.4.12: session settings and workspace hooks are separate artifacts.

Hooks in --settings are not executed by agy. The private canonical command list
is projected to .agents/hooks.json, and a native SessionStart receipt proves the
process actually loaded that projection. No operator-global files are edited.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import sys

from .opencode import private_write

HOOK_NAME = 'shantytown'


def canonical(text):
    try:
        data = json.loads(text)
        return data if isinstance(data.get('hooks'), dict) else None
    except (ValueError, TypeError, AttributeError):
        return None


def selected_config(card, root):
    from .harness import get
    program = get('agy')
    directory = Path(root) / 'settings'
    agent = directory / program.agent_settings_name(card.name)
    return agent if agent.is_file() else directory / program.settings_name(card.role)


def native_settings_path(settings_path):
    return Path(settings_path).with_name('launch-settings.json')


def write_native_settings(settings_path):
    # The canonical file contains st commands and environment metadata. The
    # provider rejects those keys; only provider-owned options cross --settings.
    path = native_settings_path(settings_path)
    private_write(path, json.dumps({'useG1Credits': False}) + '\n')
    return path


def projected_hooks(settings_path):
    command = shlex.join([sys.executable, '-m', 'shantytown.agy_hooks',
                          '--settings', str(Path(settings_path).resolve())])
    events = {e: [{'type': 'command', 'command': command + ' --event ' + e,
                   'timeout': 60}] for e in ('SessionStart', 'PreInvocation', 'Stop')}
    for event in ('PreToolUse', 'PostToolUse'):
        events[event] = [{'matcher': '.*', 'hooks': [
            {'type': 'command', 'command': command + ' --event ' + event, 'timeout': 60}]}]
    return events


def project_hooks(workspace, settings_path):
    from .provision import ProvisionError
    ws = Path(workspace).resolve()
    write_native_settings(settings_path)
    path = ws / '.agents' / 'hooks.json'
    if path.is_symlink() or (path.parent.exists() and path.parent.resolve() != ws / '.agents'):
        raise ProvisionError('agy hooks destination must stay in its workspace')
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(path.read_text()) if path.exists() else {}
        if not isinstance(data, dict):
            raise ValueError()
    except (OSError, ValueError):
        raise ProvisionError('agy workspace hooks are unreadable; preserved') from None
    data[HOOK_NAME] = projected_hooks(settings_path)
    private_write(path, json.dumps(data, indent=2) + '\n')


def translate_servers(rendered):
    from .provision import ProvisionError
    out = {}
    for name, raw in json.loads(rendered).get('mcpServers', {}).items():
        if raw.get('headersHelper'):
            raise ProvisionError('agy dynamic MCP header helper is unsupported')
        if not ('command' in raw or 'url' in raw or 'serverUrl' in raw):
            raise ProvisionError('agy MCP transport is unsupported')
        out[name] = dict(raw)
        if 'url' in out[name]:
            out[name]['serverUrl'] = out[name].pop('url')
        out[name].pop('type', None)
    return {'mcpServers': out}


def project_mcp(card, root, rendered, replace=False):
    from .provision import ProvisionError
    path = Path(card.workspace) / '.agents' / 'mcp_config.json'
    if path.is_symlink():
        raise ProvisionError('agy MCP destination cannot be a symlink')
    path.parent.mkdir(parents=True, exist_ok=True)
    before = json.loads(path.read_text()) if path.exists() else {}
    new = translate_servers(rendered)
    if not replace:
        new['mcpServers'] = {**before.get('mcpServers', {}), **new['mcpServers']}
    private_write(path, json.dumps(new, indent=2) + '\n')


def receipt_path(root, agent):
    from .crew_credentials import NAME
    if not NAME.fullmatch(agent):
        raise ValueError('invalid agy agent name')
    return Path(root) / 'agy' / 'receipts' / (agent + '.json')


def receipt_matches(root, agent, settings_path, workspace):
    """UNKNOWN or stale is never hook-ready. Caller still verifies live argv."""
    try:
        record = json.loads(receipt_path(root, agent).read_text())
        ws = Path(workspace).resolve()
        return (type(record['pid']) is int and record['pid'] > 0
                and isinstance(record['process_identity'], str) and bool(record['process_identity'])
                and record['settings'] == str(Path(settings_path).resolve())
                and record['settings_sha256'] == hashlib.sha256(Path(settings_path).read_bytes()).hexdigest()
                and record['hooks_sha256'] == hashlib.sha256((ws / '.agents/hooks.json').read_bytes()).hexdigest()
                and record['native_settings_sha256'] == hashlib.sha256(native_settings_path(settings_path).read_bytes()).hexdigest()
                and str(ws) in record['workspacePaths']
                and bool(record['conversationId'])
                and process_identity(record['pid']) == record['process_identity'])
    except (OSError, ValueError, KeyError, TypeError):
        return False


def process_identity(pid):
    """A PID alone can be recycled; start time and executable must still match."""
    import subprocess
    try:
        result = subprocess.run(['ps', '-p', str(int(pid)), '-o', 'lstart=', '-o', 'comm='],
                                capture_output=True, text=True, timeout=3, check=False)
        line = result.stdout.strip()
        return line if result.returncode == 0 and Path(line.split()[-1]).name == 'agy' else None
    except (ValueError, OSError, subprocess.SubprocessError, IndexError):
        return None


def native_process():
    import subprocess
    pid = os.getppid()
    for _ in range(6):
        identity = process_identity(pid)
        if identity:
            return pid, identity
        result = subprocess.run(['ps', '-p', str(pid), '-o', 'ppid='],
                                capture_output=True, text=True, timeout=3, check=False)
        try:
            pid = int(result.stdout.strip())
        except ValueError:
            break
        if pid <= 1:
            break
    return None, None


def live_proof(cmdline, settings_path):
    try:
        tokens = shlex.split(cmdline)
        paths = [t.split('=', 1)[1] for t in tokens if t.startswith('SHANTY_AGY_RECEIPT=')]
        if len(paths) != 1:
            return False
        path = Path(paths[0])
        record = json.loads(path.read_text())
        workspace = record['workspacePaths'][0]
        return receipt_matches(path.parent.parent.parent, path.stem, settings_path, workspace)
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return False


def is_agy_command(cmdline):
    """Read the executable position, never a model argument or directory name."""
    import re
    try:
        tokens = shlex.split(cmdline)
    except ValueError:
        return False
    if tokens[:1] == ['cd']:
        if len(tokens) < 4 or tokens[2] != '&&':
            return False
        tokens = tokens[3:]
    i = 0
    if tokens[:1] == ['env']:
        i = 1
        while i < len(tokens):
            token = tokens[i]
            if token == '-u':
                i += 2
            elif token.startswith('--unset='):
                i += 1
            elif token == '--':
                i += 1
                break
            elif re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', token):
                i += 1
            else:
                break
    else:
        while i < len(tokens) and re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', tokens[i]):
            i += 1
    return i < len(tokens) and Path(tokens[i]).name == 'agy'


def make_harness(base):
    class AgyHarness(base):
        name = 'agy'
        settings_env_var = 'SHANTY_AGY_RECEIPT'
        picker_markers = ()
        ready_patterns = ()
        stranded_markers = ()
        clear_command = None
        bypass_markers = ()

        def settings_name(self, role):
            return f'agy/{role}/settings.json'

        def agent_settings_name(self, agent):
            return f'agy/agent-{agent}/settings.json'

        def settings(self, role, root=None):
            from .runtime import claude_settings_for_role, _capture_cmd
            from .hook_bundles import apply
            data = apply(claude_settings_for_role(role, root), role, 'agy', root)
            # Never allow the operator's credit preference to create paid fallback.
            data['useG1Credits'] = False
            data['hooks'].setdefault('PostToolUse', []).append(
                {'matcher': '.*', 'hooks': [_capture_cmd(root)]})
            data['hooks'].setdefault('Stop', []).append({'hooks': [_capture_cmd(root)]})
            return data

        def launch(self, card, settings_path, root=None):
            from .harness import resolve_model, _crew_launch_identity, Unsupported
            from .runtime import _settings_env
            from .harness_options import warn_unsupported
            warn_unsupported(card, self.name)
            if not card.workspace:
                raise Unsupported('agy requires an isolated workspace for hooks')
            model = resolve_model(card, root)
            env = dict(_settings_env(card.role, root))
            options, credentials = _crew_launch_identity(card, root)
            if credentials:
                env.pop('QUIPU_AUTH_TOKEN', None)
            env.update(SHANTY_AGENT=card.name, BOBBIN_ROLE=card.role,
                       BEADS_ACTOR=card.name, ST_ROLES=','.join(card.effective_roles()))
            if root:
                env['SHANTY_AGY_RECEIPT'] = str(receipt_path(root, card.name).resolve())
                env['SHANTY_ROOT'] = str(Path(root).resolve())
            if model:
                env['SHANTY_MODEL'] = model
            if card.reports_to:
                env['ST_REPORTS_TO'] = card.reports_to
            if card.domain:
                env['ST_ROLE_DOMAIN'] = card.domain
            line = ('env -u SHANTY_MODEL -u QUIPU_SESSION -u QUIPU_MODEL -u QUIPU_HARNESS '
                    '-u CODEX_HOME -u CODEX_THREAD_ID -u CODEX_SESSION_ID '
                    '-u CLAUDECODE -u CLAUDE_CODE_SESSION_ID ') + options + credentials + ' '.join(
                f'{k}={shlex.quote(v)}' for k, v in env.items())
            line += ' agy --sandbox --settings ' + shlex.quote(str(native_settings_path(settings_path).resolve()))
            if model:
                line += ' --model ' + shlex.quote(model)
            effort = (getattr(card, 'harness_options', None) or {}).get('agy', {}).get('effort')
            if effort:
                if effort not in ('low', 'medium', 'high', 'xhigh', 'max'):
                    raise Unsupported('invalid agy effort')
                line += ' --effort ' + effort
            if card.dangerous:
                line += ' --dangerously-skip-permissions'
            return 'cd ' + shlex.quote(card.workspace) + ' && ' + line

        def settings_in_cmdline(self, cmdline):
            try:
                tokens = shlex.split(cmdline)
            except ValueError:
                return None
            if not is_agy_command(cmdline):
                return None
            for i, token in enumerate(tokens):
                if token == '--settings' and i + 1 < len(tokens):
                    path = Path(tokens[i + 1])
                    return str(path.with_name('settings.json')) if path.name == 'launch-settings.json' else str(path)
                if token.startswith('--settings='):
                    path = Path(token.split('=', 1)[1])
                    return str(path.with_name('settings.json')) if path.name == 'launch-settings.json' else str(path)
            return None

        def carries_settings(self, launch, settings_path):
            # This is our own builder, which may contain a child-shell credential
            # sanitizer. Live process sniffing uses executable-position parsing.
            tokens = shlex.split(launch)
            return any(t == '--settings' and i + 1 < len(tokens)
                       and tokens[i + 1] == str(native_settings_path(settings_path).resolve())
                       for i, t in enumerate(tokens))

        def hooks(self, card):
            from .runtime import HookSpec
            # Blocking drain requires native live acceptance, not just schema support.
            return HookSpec(blocking_stop=False)

        def provision(self, settings_path, root=None, workspaces=()):
            write_native_settings(settings_path)
            for workspace in workspaces:
                project_hooks(workspace, settings_path)
            return []

        def read_usage(self, session_path):
            # Native transcript usage has not been measured. Headless results are
            # accounted independently; never parse them as Claude deltas.
            return None

    return AgyHarness()


def doctor_rows(cards, root):
    """Pure local artifact checks. A role settings file is never a live receipt."""
    from .harness import name_for
    rows=[]
    auth=Path.home()/'.gemini/antigravity-cli/antigravity-oauth-token'
    for card in cards:
        if card.retired or name_for(card, root) != 'agy':
            continue
        config=selected_config(card, root)
        try:
            hooks_path=Path(card.workspace)/'.agents/hooks.json'
            data=json.loads(hooks_path.read_text())
            projected=data.get(HOOK_NAME)==projected_hooks(config)
        except (OSError, ValueError, TypeError):
            projected=False
        ready=bool(card.workspace) and receipt_matches(root,card.name,config,card.workspace)
        rows.append({'agent':card.name,'auth_present':auth.is_file(),
                     'hooks_projected':projected,'native_receipt':bool(ready),
                     'quota':'read configured agy_usage governor group',
                     'ready':bool(auth.is_file() and projected and ready)})
    return rows
