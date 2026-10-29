"""Minimal immutable own-job store; no controller files or credentials copied."""
import json
import os
from pathlib import Path
import stat

from .actor_identity import IdentityError
from . import job_launch

BASE = Path('/var/lib/shantytown/job-stores')


def contents(spec):
    """Render only explicit public card fields and disabled admission policy."""
    card = {key: spec[key] for key in ('workspace', 'harness')}
    card.update(name=spec['principal'], role='worker', reports_to=None, pane=None,
                dangerous=True)
    return {
        'crew/' + spec['principal'] + '.json':
            (json.dumps(card, sort_keys=True) + '\n').encode(),
        'shantytown.toml': b'[ephemeral]\nmax_agents = 0\nunattended = false\n'
                          b'require_verified_identity = true\nunattended_uid_ready = false\n',
    }


def _verify(spec, root):
    job_launch.protected(root, directory=True)
    expected = contents(spec)
    actual = set()
    for path in root.rglob('*'):
        actual.add(str(path.relative_to(root)))
        if len(actual) > len(expected) + 1:
            raise IdentityError('job metadata exceeds its fixed inventory')
    if actual != set(expected) | {'crew'}:
        raise IdentityError('job metadata contains missing or additional files')
    job_launch.protected(root / 'crew', directory=True)
    for relative, wanted in expected.items():
        path = root / relative
        job_launch.protected(path)
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as source:
            info = os.fstat(source.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != job_launch.OWNER
                    or info.st_mode & 0o022 or source.read(65537) != wanted):
                raise IdentityError('job metadata differs from its protected manifest')


def verify(spec):
    root = BASE / spec['principal']
    if str(root) != spec['root']:
        raise IdentityError('job metadata path differs from its protected manifest')
    _verify(spec, root)


def prepare(principal, digest):
    """Separate root provisioning component, never a launch-time repair.

    Installers call this only from the admitted immutable application. Interrupted
    staging directories are retained for explicit recovery; no adoption/cleanup.
    """
    if os.geteuid() != 0:
        raise IdentityError('metadata provisioning requires separately admitted root execution')
    spec, actual = job_launch.load(principal)
    if digest != actual or not any(row == spec and sha == digest for row, sha in job_launch.inventory()):
        raise IdentityError('metadata manifest is not in the protected slot plan')
    root = BASE / principal
    if str(root) != spec['root']:
        raise IdentityError('metadata store differs from protected manifest')
    job_launch.protected(BASE.parent, directory=True)
    if not BASE.exists():
        BASE.mkdir(mode=0o755)
    job_launch.protected(BASE, directory=True)
    if os.path.lexists(root):
        verify(spec)
        return 'UNCHANGED'
    staging = BASE / ('.' + principal + '.pending')
    staging.mkdir(mode=0o700)  # exclusive; interrupted state is never overwritten
    (staging / 'crew').mkdir(mode=0o755)
    for relative, raw in contents(spec).items():
        with os.fdopen(os.open(staging / relative,
                              os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644), 'wb') as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
    staging.chmod(0o755)
    _verify(spec, staging)
    for path in (staging / 'crew', staging):
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    os.rename(staging, root)
    descriptor = os.open(BASE, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return 'CREATED'
