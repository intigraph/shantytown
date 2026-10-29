"""Unprivileged installation fixtures, never a real privileged helper launch."""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def bootstrap():
    path = Path(__file__).parents[1] / 'scripts/st-job-launcher'
    scope = {'__name__': 'bootstrap_fixture', '__file__': str(path)}
    exec(compile(path.read_text(), str(path), 'exec'), scope)
    return scope


def test_combined_shebang_flags_disable_environment_and_site_processing():
    path = Path(__file__).parents[1] / 'scripts/st-job-launcher'
    assert path.read_text().splitlines()[0].endswith('python3 -IS')
    result = subprocess.run([sys.executable, '-IS', '-c',
        'import json,sys; print(json.dumps([sys.flags.isolated,sys.flags.no_site]))'],
        capture_output=True, text=True, check=True, timeout=5)
    assert json.loads(result.stdout) == [1, 1]


@pytest.mark.parametrize('fault', ['none', 'writable', 'foreign-owner', 'symlink'])
def test_application_paths_are_validated_before_import(bootstrap, tmp_path, monkeypatch, fault):
    path = tmp_path / 'application.py'
    path.write_text('raise AssertionError("must not import this fixture")')
    path.chmod(0o644)
    if fault == 'writable':
        path.chmod(0o666)
    elif fault == 'symlink':
        target = tmp_path / 'target.py'
        path.rename(target)
        path.symlink_to(target)
    original = Path.lstat
    def metadata(entry, *a, **kw):
        if entry.is_relative_to(tmp_path):
            value = original(entry, *a, **kw)
            return SimpleNamespace(st_mode=value.st_mode,
                                   st_uid=51001 if fault == 'foreign-owner' and entry == path else 0)
        # Synthetic immutable ancestry; real fixture content remains checked.
        return SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=0)
    monkeypatch.setattr(Path, 'lstat', metadata)
    if fault == 'none':
        bootstrap['protected'](path)
    else:
        with pytest.raises(RuntimeError):
            bootstrap['protected'](path)


def test_unprivileged_bootstrap_cannot_import_application(bootstrap, monkeypatch):
    monkeypatch.setattr(os, 'geteuid', lambda: 51001)
    bootstrap['protected'] = lambda *a: pytest.fail('unprivileged caller reached installation')
    with pytest.raises(RuntimeError, match='privileged isolated'):
        bootstrap['bootstrap']()
