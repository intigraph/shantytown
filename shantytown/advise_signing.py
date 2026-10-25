"""Opt-in signing profiles and observations, without an identity boundary.

The operator enables reviewed profiles; a declared actor selects one. Shared
Unix users can borrow keys, so this mode must never be called isolation. Missing
or unavailable profiles retain the original writer, before any mutation starts.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
import tomllib

POLICY_PATH = Path('/etc/shantytown/advise-signing.json')
POLICY_OWNER = 0
MAX_LOG = 16 * 1024 * 1024


def mutation(args):
    """Classify the tracker adapter's verbs, after optional global actor flags."""
    args = list(args)
    while args and args[0].startswith('--'):
        flag = args.pop(0)
        if flag in {'--actor', '--agent-name', '--harness', '--model', '--session',
                    '--quipu', '--graph', '--store', '--format', '--at'}:
            if not args:
                return False
            args.pop(0)
        elif '=' not in flag and flag not in {'--json', '--robot', '--quiet'}:
            return False
    if not args:
        return False
    if args[0] in {'comments', 'label', 'dep'}:
        return len(args) > 1 and args[1] in {'add', 'delete', 'edit', 'remove'}
    return args[0] in {'create', 'update', 'close', 'reopen', 'delete', 'defer',
                       'undefer', 'rescope', 'ack'}


def _read(path, owner, maximum, private=False):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, 'rb') as stream:
        meta = os.fstat(stream.fileno())
        if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != owner
                or meta.st_mode & (0o077 if private else 0o022)
                or meta.st_size > maximum):
            raise ValueError('unqualified file')
        raw = stream.read(maximum + 1)
        if len(raw) > maximum:
            raise ValueError('oversize file')
        return raw


def _profile(actor):
    try:
        raw = _read(POLICY_PATH, POLICY_OWNER, 65536)
    except FileNotFoundError:
        return None
    policy = json.loads(raw)
    if (not isinstance(policy, dict) or policy.get('version') != 1
            or policy.get('mode') != 'advise' or not isinstance(policy.get('profiles'), dict)):
        raise ValueError('unqualified policy')
    row = policy['profiles'].get(actor)
    if row is None:
        return None
    if not isinstance(row, dict) or set(row) != {'config_dir', 'config_sha256'}:
        raise ValueError('unqualified profile')
    root = Path(row['config_dir'])
    if not root.is_absolute() or root.is_symlink():
        raise ValueError('unqualified directory')
    for directory in (root, root / 'seeds'):
        meta = directory.lstat()
        if (not stat.S_ISDIR(meta.st_mode) or meta.st_uid != os.geteuid()
                or stat.S_IMODE(meta.st_mode) != 0o700):
            raise ValueError('unqualified directory')
    raw = _read(root / 'seeds/config.toml', os.geteuid(), 65536, private=True)
    if hashlib.sha256(raw).hexdigest() != row['config_sha256']:
        raise ValueError('profile changed')
    cfg = tomllib.loads(raw.decode())['quipu']
    if (cfg.get('require_identity') is not False
            or cfg.get('actor_principal_mode') != 'observe'
            or not all(isinstance(cfg.get(k), str) and cfg[k] for k in
                       ('signing_key_file', 'signing_session', 'signing_introducer'))):
        raise ValueError('profile is not explicitly observe-only')
    return root


def _warn():
    print('st: signing ADVISE observation UNKNOWN; original writer preserved before mutation',
          file=sys.stderr)


def _record(root, event):
    # No rotation or deletion: reaching the bound is UNKNOWN, never a quiet
    # loss of the beginning of the acceptance window. A full log cannot refuse
    # or retry the user's already-completed mutation.
    import fcntl
    fd = os.open(root / 'writes.jsonl', os.O_WRONLY | os.O_APPEND | os.O_CREAT
                 | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, 0o600)
    try:
        meta = os.fstat(fd)
        raw = (json.dumps(event, sort_keys=True) + '\n').encode()
        if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.geteuid()
                or meta.st_mode & 0o077 or len(raw) > 4096):
            raise ValueError('unqualified observation log')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if os.fstat(fd).st_size + len(raw) > MAX_LOG or os.write(fd, raw) != len(raw):
            raise ValueError('observation log unavailable')
        os.fsync(fd)
    finally:
        os.close(fd)


def run(command, *, actor, asserted_actor, identity_command, options, runner):
    """Run the mutation exactly once; observations never imply it committed."""
    try:
        root = _profile(actor)
    except (OSError, ValueError, KeyError, TypeError):
        _warn()
        return runner(command, **options)
    if root is None:
        return runner(command, **options)
    selected = dict(options)
    original_env = options.get('env')
    selected['env'] = dict(os.environ if original_env is None else original_env,
                           XDG_CONFIG_HOME=str(root))
    event = {'version': 1, 'actor': asserted_actor, 'profile_actor': actor,
             'at': time.time(), 'principal': None,
             'authenticated': False, 'selection': 'legacy', 'command_exit': None}
    try:
        probe_options = dict(selected, timeout=min(options.get('timeout', 10), 10))
        probe = runner(identity_command, **probe_options)
        identity = json.loads(probe.stdout) if probe.returncode == 0 else None
        if (not isinstance(identity, dict) or identity.get('authenticated') is not True
                or identity.get('auth_class') != 'attested_session'
                or not isinstance(identity.get('principal'), str)
                or not identity['principal'] or len(identity['principal']) > 128
                or not re.fullmatch(r'sha256:[0-9a-f]{64}', identity.get('key_id', ''))
                or identity.get('session') != tomllib.loads(
                    _read(root / 'seeds/config.toml', os.geteuid(), 65536, True).decode()
                )['quipu']['signing_session']):
            raise ValueError('identity unqualified')
        if _profile(actor) != root:
            raise ValueError('profile changed during identity read')
        event.update(principal=identity['principal'], key_id=identity['key_id'],
                     session=identity['session'], authenticated=True, selection='profile')
    except Exception:
        # This is preflight, not a failed mutation. Preserve legacy availability
        # and record the gap; it cannot count toward a zero-mismatch window.
        selected = options
        _warn()
    try:
        result = runner(command, **selected)
        event['command_exit'] = result.returncode
        return result
    finally:
        event['match'] = event['authenticated'] and event['principal'] == asserted_actor
        try:
            _record(root, event)
        except Exception:
            print('st: signing ADVISE write observation UNKNOWN; command was not retried',
                  file=sys.stderr)
