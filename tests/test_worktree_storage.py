"""Mounted storage admission must fail before worktree creation."""
from pathlib import Path
import json
import subprocess
import pytest
from shantytown import worktree_storage as storage
from shantytown import workspace


def admitted(tmp_path, **kwargs):
    mount = tmp_path / 'disk'
    mount.mkdir(exist_ok=True)
    env = {'SHANTY_WORKTREE_ROOT': str(mount / 'trees'),
           'SHANTY_WORKTREE_MOUNT': str(mount)}
    return storage.configured_root(environ=env, mountpoint=lambda p: True,
                                   device=lambda p: 1 if p == Path('/') else 2,
                                   **kwargs)


def test_admission_does_not_create_storage(tmp_path):
    root = admitted(tmp_path)
    assert root == tmp_path / 'disk/trees'
    assert not root.exists()


@pytest.mark.parametrize('env', [
    {'SHANTY_WORKTREE_ROOT': ''},
    {'SHANTY_WORKTREE_ROOT': '/mnt/trees'},
    {'SHANTY_WORKTREE_MOUNT': '/mnt'},
    {'SHANTY_WORKTREE_ROOT': 'relative', 'SHANTY_WORKTREE_MOUNT': '/mnt'},
    {'SHANTY_WORKTREE_ROOT': '/outside', 'SHANTY_WORKTREE_MOUNT': '/mnt'},
])
def test_invalid_explicit_selection_never_falls_back(env):
    with pytest.raises(storage.StorageError):
        storage.configured_root(environ=env)


@pytest.mark.parametrize('mounted,root_device', [(False, 2), (True, 1)])
def test_missing_or_root_filesystem_refuses(tmp_path, mounted, root_device):
    with pytest.raises(storage.StorageError):
        storage.configured_root(environ={'SHANTY_WORKTREE_ROOT': str(tmp_path),
            'SHANTY_WORKTREE_MOUNT': str(tmp_path)},
            mountpoint=lambda p: mounted,
            device=lambda p: 1 if p == Path('/') else root_device)


def test_config_and_same_name_collision(tmp_path):
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'schema': 1, 'root': str(tmp_path / 'trees'),
                                 'mount': str(tmp_path)}))
    root = storage.configured_root(environ={}, config_path=config,
        mountpoint=lambda p: True, device=lambda p: 1 if p == Path('/') else 2)
    assert storage.destination(root, tmp_path / 'a/project', 'worker') != storage.destination(root, tmp_path / 'b/project', 'worker')


def test_missing_mount_prevents_add(tmp_path, monkeypatch):
    repo = tmp_path / 'project'
    (repo / '.git').mkdir(parents=True)
    monkeypatch.setenv('SHANTY_WORKTREE_ROOT', str(tmp_path / 'absent/trees'))
    monkeypatch.setenv('SHANTY_WORKTREE_MOUNT', str(tmp_path / 'absent'))
    calls = []
    with pytest.raises(workspace.WorkspaceError):
        workspace.ensure_worktree(repo, 'worker', add=lambda *args: calls.append(args))
    assert calls == []
    assert not (tmp_path / 'absent').exists()


def test_existing_legacy_tree_survives_missing_mount(tmp_path, monkeypatch):
    repo = tmp_path / 'project'
    tree = tmp_path / 'project-wt/worker'
    tree.mkdir(parents=True)
    monkeypatch.setenv('SHANTY_WORKTREE_ROOT', '')
    assert workspace.worktree_for(repo, 'worker') == tree


def test_registered_external_tree_survives_config_removal(tmp_path, monkeypatch):
    import subprocess
    repo = tmp_path / 'project'
    repo.mkdir()
    def git(*args):
        return subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', '-C', str(repo), *args],
                              check=True, capture_output=True, text=True)
    git('init')
    git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
        'commit', '--allow-empty', '-m', 'fixture')
    root = tmp_path / 'external'
    target = storage.destination(root, repo, 'worker')
    target.parent.mkdir(parents=True)
    git('worktree', 'add', '-b', 'worker', str(target))
    monkeypatch.setattr(storage, 'configured_root', lambda: None)
    assert workspace.worktree_for(repo, 'worker') == target
    assert workspace.worktree_for(target, 'worker') == target
    assert workspace.worktree_for(target.parent, 'worker') == target
    assert workspace.ensure_worktree(repo, 'worker', add=lambda *a: pytest.fail('duplicate add')) == str(target)
    import shutil
    shutil.rmtree(target)
    with pytest.raises(workspace.WorkspaceError, match='unavailable'):
        workspace.ensure_worktree(repo, 'worker', add=lambda *a: pytest.fail('duplicate add'))


def test_foreign_existing_destination_refuses(tmp_path, monkeypatch):
    repo = tmp_path / 'project'
    (repo / '.git').mkdir(parents=True)
    root = tmp_path / 'storage'
    destination = storage.destination(root, repo, 'worker')
    destination.mkdir(parents=True)
    monkeypatch.setattr(storage, 'configured_root', lambda: root)
    with pytest.raises(workspace.WorkspaceError, match='not registered'):
        workspace.ensure_worktree(repo, 'worker', add=lambda *a: pytest.fail('must not add'))


def test_broken_config_symlink_refuses(tmp_path):
    config = tmp_path / 'config'
    config.symlink_to(tmp_path / 'missing')
    with pytest.raises(storage.StorageError, match='symlink'):
        storage.configured_root(environ={}, config_path=config)


def test_external_enumeration_and_provisioning_agree(tmp_path, monkeypatch):
    root = tmp_path / 'storage'
    repo = tmp_path / 'project'
    (repo / '.git').mkdir(parents=True)
    monkeypatch.setattr(storage, 'configured_root', lambda: root)
    monkeypatch.setenv('GT_ROOT', str(tmp_path / 'gt'))
    monkeypatch.setenv('WORKSPACE_ROOT', str(tmp_path / 'workspace'))
    def add(shared, dest, agent, base):
        dest.mkdir(parents=True)
        (dest / '.git').write_text('gitdir: private-fixture')
    created = Path(workspace.ensure_worktree(repo, 'worker', add=add))
    assert created.parent.parent == root
    assert workspace.agent_worktrees('worker') == [created]
    assert not (tmp_path / 'project-wt').exists()


@pytest.mark.parametrize('body', ['[]', '{}', '{"schema":2,"root":"/mnt/x","mount":"/mnt"}', 'not json'])
def test_malformed_configuration_refuses(tmp_path, body):
    config = tmp_path / 'config'
    config.write_text(body)
    with pytest.raises(storage.StorageError):
        storage.configured_root(environ={}, config_path=config)


def test_source_symlink_alias_has_one_storage_identity(tmp_path):
    source = tmp_path / 'actual'
    source.mkdir()
    alias = tmp_path / 'alias'
    alias.symlink_to(source, target_is_directory=True)
    root = tmp_path / 'storage'
    assert storage.destination(root, source, 'worker') == storage.destination(root, alias, 'worker')


def identity_repository(tmp_path, kind):
    repo = tmp_path / 'project'
    repo.mkdir()
    metadata = tmp_path / 'metadata'
    args = ['git', '-c', 'core.hooksPath=/dev/null', 'init']
    if kind == 'separate':
        args += ['--separate-git-dir', str(metadata)]
    subprocess.run([*args, str(repo)], check=True, capture_output=True)
    if kind == 'symlink':
        (repo / '.git').rename(metadata)
        (repo / '.git').symlink_to(metadata, target_is_directory=True)

    def git(*args):
        return subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', '-C', str(repo), *args],
                              check=True, capture_output=True, text=True)

    git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
        'commit', '--allow-empty', '-m', 'fixture')
    tree = tmp_path / 'project-wt/worker'
    git('worktree', 'add', '-b', 'worker', str(tree))
    return repo, tree, git


@pytest.mark.parametrize('kind', ['ordinary', 'separate', 'symlink'])
@pytest.mark.parametrize('input_name', ['source', 'linked'])
def test_primary_identity_does_not_depend_on_metadata_name(tmp_path, monkeypatch, kind, input_name):
    repo, tree, _ = identity_repository(tmp_path, kind)
    monkeypatch.setattr(storage, 'configured_root', lambda: None)
    path = repo if input_name == 'source' else tree
    assert workspace._shared_repo(path).resolve() == repo.resolve()
    assert workspace.worktree_for(path, 'worker') == tree


@pytest.mark.parametrize('kind', ['separate', 'symlink'])
def test_unknown_external_primary_refuses_before_add(tmp_path, monkeypatch, kind):
    repo, _, _ = identity_repository(tmp_path, kind)
    root = tmp_path / 'storage'
    monkeypatch.setattr(storage, 'configured_root', lambda: root)
    with pytest.raises(workspace.WorkspaceError, match='registered primary'):
        workspace.ensure_worktree(repo, 'new-worker', add=lambda *a: pytest.fail('must not add'))
    assert not root.exists()


@pytest.mark.parametrize('kind', ['separate', 'symlink'])
def test_unknown_registered_external_tree_never_creates_a_duplicate(tmp_path, monkeypatch, kind):
    repo, _, git = identity_repository(tmp_path, kind)
    target = storage.destination(tmp_path / 'external', repo, 'external-worker')
    git('worktree', 'add', '-b', 'external-worker', str(target))
    monkeypatch.setattr(storage, 'configured_root', lambda: None)
    with pytest.raises(workspace.WorkspaceError, match='one shared checkout'):
        workspace.ensure_worktree(repo, 'external-worker', add=lambda *a: pytest.fail('duplicate add'))
    assert target.exists()
    assert not (tmp_path / 'project-wt/external-worker').exists()


def test_foreign_legacy_name_cannot_override_registered_identity(tmp_path):
    repo, _, git = identity_repository(tmp_path, 'ordinary')
    foreign = tmp_path / 'foreign'
    subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', 'init', str(foreign)],
                   check=True, capture_output=True)
    tree = tmp_path / 'foreign-wt/other-worker'
    git('worktree', 'add', '-b', 'other-worker', str(tree))
    assert workspace._shared_repo(tree).resolve() == repo.resolve()


def test_ambiguous_primary_alias_is_not_chosen(tmp_path):
    repo, _, git = identity_repository(tmp_path, 'ordinary')
    alias = tmp_path / 'alias'
    alias.mkdir()
    (alias / '.git').write_text(f'gitdir: {repo / ".git"}\n')
    tree = tmp_path / 'alias-wt/other-worker'
    git('worktree', 'add', '-b', 'other-worker', str(tree))
    with pytest.raises(workspace.WorkspaceError, match='one shared checkout'):
        workspace._shared_repo(tree)
