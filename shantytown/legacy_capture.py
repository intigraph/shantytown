"""Verify inherited graph-capture registrations; the installer owns deployment.

# arming: library — provision checks inherited registrations before projection.
No hook is installed, registered, or executed here.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
import tomllib

RECEIPT = '.shantytown-legacy-session-capture.json'
HOOK = 'quipu-session-capture.sh'


def inspect(ws: Path, manifest, settings_path=None) -> dict | None:
    """Return byte proof, or refuse an unverifiable active legacy registration."""
    home = Path.home()
    canonical = home / '.gt' / 'hooks' / HOOK
    paths = [home / '.claude' / 'settings.json',
             ws / '.claude' / 'settings.json',
             ws / '.claude' / 'settings.local.json',
             ws.parent / '.claude' / 'settings.json',
             home / '.gt' / 'hooks-overrides' /
             f'{ws.parent.parent.name}__{ws.parent.name}.json']
    if settings_path is not None:
        paths.append(Path(settings_path))
    registrations = []
    for path in dict.fromkeys(paths):
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            continue
        except OSError:
            raise ValueError('legacy session-capture registration is unreadable') from None
        # Preserve unrelated non-JSON templates. Never report their contents.
        if HOOK.encode() not in raw:
            continue
        try:
            data = (tomllib.loads(raw.decode()) if path.suffix == '.toml'
                    else json.loads(raw))
            hooks = data.get('hooks', data)
            groups = hooks.get('Stop', [])
            commands = [h.get('command', '') for g in groups
                        for h in g.get('hooks', [])]
            expanded = [str(c).replace('${HOME}', str(home))
                        .replace('$HOME', str(home)).replace('~/', str(home) + '/')
                        for c in commands]
            pattern = re.escape(str(canonical)) + r"(?=$|[\s\"';)&|])"
            active = any(re.search(pattern, c) for c in expanded)
        except (ValueError, AttributeError, TypeError, UnicodeError):
            raise ValueError('legacy session-capture registration cannot be verified') from None
        if active:
            registrations.append({'path': str(path),
                                  'sha256': hashlib.sha256(raw).hexdigest()})
    if not registrations:
        return {'status': 'unregistered'} if (ws / RECEIPT).exists() else None
    source_dir = (dict(manifest.sources(ws)).get('graph-capture')
                  if manifest is not None else ws / 'skills' / 'graph-capture')
    source = source_dir / 'hooks' / HOOK if source_dir is not None else None
    remedy = ('legacy session-capture is stale or unverifiable; use the declared '
              'graph-capture install-graph-capture-hook.sh --check / --install '
              'or explicitly retire its registration')
    try:
        if source is None or not (source_dir / 'SKILL.md').is_file():
            raise ValueError(remedy)
        if canonical.is_symlink() or not canonical.is_file() or not os.access(canonical, os.X_OK):
            raise ValueError(remedy)
        expected = hashlib.sha256(source.read_bytes()).hexdigest()
        observed = hashlib.sha256(canonical.read_bytes()).hexdigest()
        if expected != observed:
            raise ValueError(remedy)
    except OSError:
        raise ValueError(remedy) from None
    return {'status': 'verified', 'source': str(source),
            'canonical': str(canonical), 'source_sha256': expected,
            'canonical_sha256': observed, 'registrations': registrations}


def record(ws: Path, proof: dict | None) -> None:
    if proof is not None:
        from .files import write_text_atomic
        path = ws / RECEIPT
        if path.is_symlink():
            raise ValueError('legacy session-capture receipt must not be a symlink')
        text = json.dumps(proof, indent=2) + '\n'
        if not path.exists() or path.read_text() != text:
            write_text_atomic(path, text)
