"""Disposable metadata reproducer. Trust anchors mocked; no native UID change."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[3])
args = parser.parse_args()
sys.path.insert(0, str(args.source.resolve()))
if importlib.util.find_spec('shantytown.job_metadata') is None:
    print('Before: no protected own-job metadata preparation component')
    raise SystemExit(0)
from shantytown import job_metadata, job_launch
from shantytown.actor_identity import IdentityError

print('Synthetic fixture: substituted trust anchors, no native account or UID operation')
with tempfile.TemporaryDirectory() as directory:
    base = Path(directory)
    principal = 'eph-task-123abc'
    spec = dict(principal=principal, root=str(base / 'stores' / principal),
                workspace='/synthetic-own-home/worktree', harness='codex',
                controller_root='/synthetic-controller-private-store')
    digest = 'a' * 64
    owner = os.geteuid()
    def fixture_protected(path, **kwargs):
        path = Path(path)
        if (not path.is_relative_to(base) or path.is_symlink()
                or path.lstat().st_uid != owner or path.lstat().st_mode & 0o022):
            raise IdentityError('untrusted fixture path')
    with patch.object(job_metadata, 'BASE', base / 'stores'), \
            patch.object(job_launch, 'OWNER', owner), \
            patch.object(job_launch, 'protected', fixture_protected), \
            patch.object(job_launch, 'load', return_value=(spec, digest)), \
            patch.object(job_launch, 'inventory', return_value=[(spec, digest)]), \
            patch.object(job_launch.os, 'geteuid', return_value=0):
        print('prepare exact slot:', job_metadata.prepare(principal, digest))
        root = Path(spec['root'])
        print('files:', ', '.join(sorted(p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file())))
        card = json.loads((root / 'crew' / (principal + '.json')).read_text())
        print('own principal:', card['name'], '; controller fields:', card['reports_to'], card['pane'])
        print((root / 'shantytown.toml').read_text().strip())
        print('identical retry:', job_metadata.prepare(principal, digest))
        (root / 'foreign-file').write_text('synthetic unexpected data')
        try:
            job_metadata.prepare(principal, digest)
        except IdentityError:
            print('extra-file control: REFUSED; unexpected file retained')
        else:
            raise AssertionError('unexpected metadata was adopted')
