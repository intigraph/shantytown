"""Key-derived actors under an operator-owned, Unix-UID-bound policy.

Environment names are declarations, never credentials. No cryptography is
implemented here: sd signs the existing Quipu session-attestation protocol and
resolves its principal through the protected server registry. No private key is
read by this module. Distinct Unix users remain a deployment prerequisite.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

POLICY_PATH = (Path('/Library/Application Support/Shantytown/identity.json')
               if sys.platform == 'darwin' else Path('/etc/shantytown/identity.json'))
TRUSTED_POLICY_OWNER = 0

class IdentityError(RuntimeError):
    pass

def _policy(path: Path, *, for_principal=None):
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0))
    except FileNotFoundError:
        return None
    except OSError as error:
        raise IdentityError('cannot open protected identity policy') from error
    with os.fdopen(fd, 'rb') as stream:
        meta = os.fstat(stream.fileno())
        if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != TRUSTED_POLICY_OWNER
                or meta.st_mode & 0o022 or meta.st_size > 1024 * 1024):
            raise IdentityError('identity policy must be an operator-owned regular non-writable file')
        try:
            data = json.load(stream)
        except (ValueError, OSError) as error:
            raise IdentityError('invalid protected identity policy') from error
    if not isinstance(data, dict) or data.get('version') != 1 or data.get('required') is not True:
        raise IdentityError('invalid protected identity policy version/required flag')
    users = data.get('users')
    selected_uid = str(os.geteuid())
    if for_principal is None and int(selected_uid) < 10000:
        raise IdentityError('agent identity requires a dedicated Unix UID; shared login is not isolation')
    if for_principal is not None:
        matches = [(uid, row) for uid, row in users.items()
                   if isinstance(row, dict) and row.get('principal') == for_principal] if isinstance(users, dict) else []
        if len(matches) != 1:
            raise IdentityError('launch principal has no unique protected Unix binding')
        selected_uid, row = matches[0]
        if not selected_uid.isdecimal() or int(selected_uid) < 10000:
            raise IdentityError('launch requires an unprivileged dedicated Unix UID')
        if os.geteuid() not in (0, int(selected_uid)):
            raise IdentityError('caller cannot launch a different agent Unix identity')
    else:
        row = users.get(selected_uid) if isinstance(users, dict) else None
    if (not isinstance(row, dict) or set(row) != {'principal', 'home', 'endpoint', 'sd'}
            or not all(isinstance(v, str) and v and not any(c in v for c in '\r\n\0') for v in row.values())
            or not Path(row['home']).is_absolute() or not Path(row['sd']).is_absolute()
            or not row['endpoint'].startswith('https://')):
        raise IdentityError('current Unix UID has no valid protected identity binding')
    return dict(row, uid=int(selected_uid)) if for_principal is not None else row

def authenticated_actor(*, policy_path=None, run=None):
    """Return a verified principal, None for unmigrated hosts, or fail closed."""
    row = _policy(POLICY_PATH if policy_path is None else Path(policy_path))
    if row is None:
        return None
    run = subprocess.run if run is None else run
    # Pin the endpoint, home and working directory. A project config, daemon
    # environment or actor flag cannot redirect this authentication request.
    env = {k: v for k, v in os.environ.items() if not k.startswith(('SEEDS_', 'QUIPU_', 'XDG_'))}
    env['HOME'] = row['home']
    try:
        answer = run([row['sd'], '--quipu', row['endpoint'], 'identity', '--json'],
                     cwd=row['home'], env=env, capture_output=True, text=True, timeout=20)
        value = json.loads(answer.stdout) if answer.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError) as error:
        raise IdentityError('authenticated actor unavailable; nothing attributed') from error
    if (not isinstance(value, dict) or value.get('authenticated') is not True
            or value.get('auth_class') != 'attested_session' or value.get('principal') != row['principal']
            or not isinstance(value.get('key_id'), str) or not value['key_id'].startswith('sha256:')
            or not isinstance(value.get('session'), str) or not value['session']):
        raise IdentityError('key-derived actor does not match the protected Unix UID binding')
    for variable in ('SHANTY_AGENT', 'SEEDS_ACTOR', 'QUIPU_AGENT'):
        claim = os.environ.get(variable, '').strip()
        if claim and claim != value['principal']:
            raise IdentityError(f'{variable} differs from authenticated principal')
    return value['principal']
