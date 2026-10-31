"""Real Git/API controls for preserved private scratch, never a live PR writer."""
import json
from pathlib import Path
import stat
import subprocess

import pytest

from shantytown import pr_preflight as p
from test_pr_preflight import Forge, REPO


class World(Forge):
    def __init__(self, root, tracked=False):
        super().__init__()
        self.root = root
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.email', 'test@example.org')
        self.git('config', 'user.name', 'Test')
        (root / 'source.py').write_text('base\n')
        if tracked:
            for name in ('.work', '.task-notes'):
                (root / name).mkdir()
                (root / name / 'tracked').write_text('base\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'base')
        self.base = self.git('rev-parse', 'HEAD').decode().strip()
        self.git('checkout', '-qb', 'feature')
        (root / 'source.py').write_text('candidate\n')
        self.git('commit', '-qam', 'candidate')
        self.head = self.git('rev-parse', 'HEAD').decode().strip()
        self.git('remote', 'add', 'origin', 'https://github.com/example/project.git')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.PIPE)

    def __call__(self, path, body=None):
        if path.startswith(f'repos/{REPO}/commits/'):
            return {'sha': self.head if path.endswith('/feature') else self.base}
        result = super().__call__(path, body)
        if body is not None:
            result['head']['sha'], result['base']['sha'] = self.head, self.base
        return result

    def create(self):
        return p.run(self.root, REPO, 'main', 'project-scratch', 'Concrete source change',
                     'fix(preflight): preserve scratch', [], create=True, api=self)


def snapshot(world):
    files = {}
    for name in ('.work', '.task-notes'):
        root = world.root / name
        if root.is_dir() and not root.is_symlink():
            for path in (root, *root.rglob('*')):
                files[str(path.relative_to(world.root))] = (
                    stat.S_IMODE(path.lstat().st_mode), path.read_bytes() if path.is_file() else None)
    return files, world.git('status', '--porcelain=v1', '-z', '--untracked-files=all')


@pytest.mark.parametrize('name', ['.work', '.task-notes'])
@pytest.mark.parametrize('filename', ['note', 'nested/space and "quote"', 'line\n?? unrelated\rname'])
def test_real_create_preserves_private_scratch_without_metadata_or_output(tmp_path, capsys, name, filename):
    world = World(tmp_path)
    note = tmp_path / name / filename
    note.parent.mkdir(parents=True)
    note.write_bytes(b'inert-private-content-must-not-publish')
    note.chmod(0o600)
    (tmp_path / name).chmod(0o700)
    before = snapshot(world)
    result = world.create()
    assert len(world.writes) == 1 and result['candidate']['files'] == ['source.py']
    assert snapshot(world) == before
    emitted = json.dumps(result) + json.dumps(world.writes) + ''.join(capsys.readouterr())
    assert name not in emitted and filename not in emitted
    assert 'inert-private-content' not in emitted


@pytest.mark.parametrize('path', ['other', '.work-copy/note', '.task-notes-copy/note',
                                 'nested/.work/note', 'nested/.task-notes/note',
                                 'other\n?? .work/note'])
def test_unrelated_and_lookalike_untracked_paths_refuse(tmp_path, path):
    world = World(tmp_path)
    note = tmp_path / path
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text('inert private note')
    before = world.git('status', '--porcelain=v1', '-z', '--untracked-files=all')
    with pytest.raises(p.Refused, match='commit candidate'):
        world.create()
    assert world.git('status', '--porcelain=v1', '-z', '--untracked-files=all') == before
    assert not world.writes


@pytest.mark.parametrize('name', ['.work', '.task-notes'])
@pytest.mark.parametrize('kind', ['file', 'symlink'])
def test_scratch_root_must_be_directory_without_following_symlink(tmp_path, name, kind):
    root = tmp_path / 'repo'
    root.mkdir()
    world = World(root)
    outside = tmp_path / 'outside'
    outside.mkdir()
    target = outside / 'note'
    target.write_bytes(b'outside-inert-note')
    if kind == 'symlink':
        (root / name).symlink_to(outside, target_is_directory=True)
    else:
        (root / name).write_text('not a directory')
    before = (target.read_bytes(), target.stat().st_mode, (root / name).lstat())
    with pytest.raises(p.Refused, match='commit candidate'):
        world.create()
    assert (target.read_bytes(), target.stat().st_mode, (root / name).lstat()) == before
    assert not world.writes


@pytest.mark.parametrize('name', ['.work', '.task-notes'])
@pytest.mark.parametrize('change', ['modified', 'staged', 'deleted', 'renamed', 'staged-new'])
def test_all_tracked_and_index_scratch_changes_refuse(tmp_path, name, change):
    world = World(tmp_path, tracked=True)
    path = tmp_path / name / 'tracked'
    if change in ('modified', 'staged'):
        path.write_text('changed\n')
        if change == 'staged':
            world.git('add', name)
    elif change == 'deleted':
        path.unlink()
    elif change == 'renamed':
        world.git('mv', f'{name}/tracked', f'{name}/renamed')
    else:
        (tmp_path / name / 'new').write_text('new\n')
        world.git('add', name)
    before = snapshot(world)
    with pytest.raises(p.Refused, match='commit candidate'):
        world.create()
    assert snapshot(world) == before and not world.writes


def test_unmerged_scratch_refuses(tmp_path):
    world = World(tmp_path, tracked=True)
    world.git('checkout', '-qb', 'side', world.base)
    (tmp_path / '.work/tracked').write_text('side\n')
    world.git('commit', '-qam', 'side')
    world.git('checkout', '-q', 'feature')
    (tmp_path / '.work/tracked').write_text('feature\n')
    world.git('commit', '-qam', 'feature')
    result = subprocess.run(['git', '-C', str(tmp_path), 'merge', 'side'], capture_output=True)
    assert result.returncode == 1 and b'UU .work/tracked\0' in snapshot(world)[1]
    before = snapshot(world)
    with pytest.raises(p.Refused, match='commit candidate'):
        world.create()
    assert snapshot(world) == before and not world.writes


@pytest.mark.parametrize('raw', [b'XY .work/note\0', b'?? .work/note', b'?? .work/../other\0',
                                 b'?? .work//note\0', b'?? .work/note\0\0', b'?? \0'])
def test_unknown_or_malformed_status_cannot_admit(tmp_path, monkeypatch, raw):
    world = World(tmp_path)
    (tmp_path / '.work').mkdir()
    original = subprocess.run
    def run(argv, *args, **kwargs):
        if 'status' in argv:
            return subprocess.CompletedProcess(argv, 0, raw if not kwargs.get('text') else raw.decode(), b'')
        return original(argv, *args, **kwargs)
    monkeypatch.setattr(p.subprocess, 'run', run)
    with pytest.raises(p.Refused, match='commit candidate'):
        world.create()
    assert not world.writes


def test_private_exception_keeps_exact_head_gate(tmp_path):
    world = World(tmp_path)
    (tmp_path / '.work').mkdir()
    (tmp_path / '.work/note').write_text('inert')
    world.head = world.base  # API reports an unpublished candidate.
    with pytest.raises(p.Refused, match='exact candidate'):
        world.create()
    assert not world.writes


@pytest.mark.parametrize('name', ['.work', '.task-notes'])
def test_private_nested_repository_directory_record_is_preserved(tmp_path, name):
    world = World(tmp_path)
    nested = tmp_path / name / 'nested-repo'
    nested.mkdir(parents=True)
    subprocess.run(['git', '-C', str(nested), 'init', '-q'], check=True)
    (nested / 'note').write_text('inert nested private bytes')
    before = snapshot(world)
    assert before[1].endswith(b'/\0')
    assert world.create()['candidate']['files'] == ['source.py']
    assert snapshot(world) == before


def test_private_files_are_not_opened_by_preflight(tmp_path, monkeypatch):
    world = World(tmp_path)
    private = tmp_path / '.work'
    private.mkdir()
    (private / 'note').write_text('inert private bytes')
    original = Path.open
    def opened(path, *args, **kwargs):
        assert not path.is_relative_to(private), 'preflight tried to open private contents'
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', opened)
    assert world.create()['candidate']['files'] == ['source.py']


def test_private_exception_does_not_hide_other_tracked_changes(tmp_path):
    world = World(tmp_path)
    (tmp_path / '.work').mkdir()
    (tmp_path / '.work/note').write_text('inert')
    (tmp_path / 'source.py').write_text('uncommitted\n')
    before = snapshot(world)
    with pytest.raises(p.Refused, match='commit candidate'):
        world.create()
    assert snapshot(world) == before and not world.writes


def test_unverifiable_scratch_root_fails_closed_without_private_error_text(tmp_path, monkeypatch):
    world = World(tmp_path)
    private = tmp_path / '.work'
    private.mkdir()
    (private / 'note').write_text('inert')
    original = Path.lstat
    def lstat(path, *args, **kwargs):
        if path == private:
            raise PermissionError('inert-private-error-must-not-escape')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'lstat', lstat)
    with pytest.raises(p.Refused, match='commit candidate') as error:
        world.create()
    assert 'private-error' not in str(error.value) and error.value.__suppress_context__
    assert not world.writes


@pytest.mark.parametrize('code,stderr', [(1, b''), (0, b'warning: unreadable untracked directory')])
def test_incomplete_git_status_refuses_without_disclosing_stderr(tmp_path, monkeypatch, code, stderr):
    world = World(tmp_path)
    original = subprocess.run
    def run(argv, *args, **kwargs):
        if 'status' in argv:
            return subprocess.CompletedProcess(argv, code, b'', stderr)
        return original(argv, *args, **kwargs)
    monkeypatch.setattr(p.subprocess, 'run', run)
    with pytest.raises(p.Refused, match='commit candidate') as error:
        world.create()
    assert 'unreadable' not in str(error.value) and not world.writes


@pytest.mark.parametrize('name', ['.work', '.task-notes'])
def test_subdirectory_checkout_checks_repository_root(tmp_path, name):
    world = World(tmp_path)
    subdirectory = tmp_path / 'subdirectory'
    subdirectory.mkdir()
    private = tmp_path / name
    private.mkdir()
    (private / 'note').write_text('inert')
    before = snapshot(world)
    result = p.run(subdirectory, REPO, 'main', 'project-scratch', 'Concrete change',
                   'Fixture', [], create=True, api=world)
    assert result['candidate']['files'] == ['source.py']
    assert len(world.writes) == 1 and snapshot(world) == before
