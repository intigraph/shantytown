"""Optional mounted storage for newly provisioned project worktrees."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


class StorageError(ValueError):
    pass


def configured_root(*, environ=None, config_path=None, mountpoint=None, device=None):
    """Return an admitted root or None; explicit invalid choices never fall back."""
    env = os.environ if environ is None else environ
    if 'SHANTY_WORKTREE_ROOT' in env or 'SHANTY_WORKTREE_MOUNT' in env:
        values = {'root': env.get('SHANTY_WORKTREE_ROOT'),
                  'mount': env.get('SHANTY_WORKTREE_MOUNT')}
    else:
        path = config_path or Path(env.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'shantytown/worktree-storage.json'
        path = Path(path)
        if path.is_symlink():
            raise StorageError('storage configuration must not be a symlink')
        if not path.exists():
            return None
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            raise StorageError('storage configuration is unreadable or malformed') from exc
        if not isinstance(record, dict) or set(record) != {'schema', 'root', 'mount'} or record['schema'] != 1:
            raise StorageError('storage configuration must have schema 1, root and mount')
        values = record
    if any(not isinstance(values.get(k), str) or not values[k].strip() for k in ('root', 'mount')):
        raise StorageError('both nonempty storage root and required mount are mandatory')
    root, mount = (Path(values[k]).expanduser() for k in ('root', 'mount'))
    if not root.is_absolute() or not mount.is_absolute():
        raise StorageError('storage paths must be absolute')
    root, mount = root.resolve(), mount.resolve()
    if mount not in root.parents and root != mount:
        raise StorageError('storage root must be beneath its required mount')
    mounted = os.path.ismount if mountpoint is None else mountpoint
    dev = (lambda p: p.stat().st_dev) if device is None else device
    if not mounted(mount) or dev(mount) == dev(Path('/')):
        raise StorageError('required storage is not a separate mounted filesystem')
    existing = root
    while not existing.exists():
        existing = existing.parent
    if dev(existing) != dev(mount):
        raise StorageError('storage root resolves onto a different filesystem')
    if root.exists() and not root.is_dir():
        raise StorageError('storage root is not a directory')
    return root


def destination(root: Path, shared: Path, agent: str) -> Path:
    # The entire source identity distinguishes same-named checkouts. The digest
    # is a filesystem namespace, never authentication or a public identifier.
    identity = hashlib.sha256(os.fsencode(shared.resolve())).hexdigest()
    return root / f'{shared.name[:48]}-{identity}-wt' / agent
