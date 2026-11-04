"""--gc on a RELOCATED (symlinked) worktree must never delete anything (aegis-5ox).

Root relief moved cold worktrees off the root filesystem and left a symlink at
the original path. `git worktree remove <symlink>` then deletes every file THROUGH
the link and only afterwards fails on the link itself, and the CLI used to print
that as "refused:". These tests use REAL git, because the defect lives in git's
behaviour, which an injected remover cannot reproduce.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from shantytown.workspace import (WorkspaceError, WorktreeDamage,
                                  cleanup_worktree, git_worktree_remove)

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def _git(*args, cwd=None):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _relocated_worktree(tmp_path):
    """A shared repo with agent billy's clean worktree moved behind a symlink."""
    shared = tmp_path / "proj"
    shared.mkdir()
    _git("init", "-q", "-b", "main", cwd=shared)
    _git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
         "--allow-empty", "-m", "base", cwd=shared)
    (shared / "f.txt").write_text("tracked\n")
    _git("add", "f.txt", cwd=shared)
    _git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "f", cwd=shared)
    _git("update-ref", "refs/remotes/origin/main", "HEAD", cwd=shared)
    dest = tmp_path / "proj-wt" / "billy"
    dest.parent.mkdir()
    _git("worktree", "add", "-q", "-b", "wt/billy", str(dest), "main", cwd=shared)
    # Relocate exactly as root relief did: move the tree, symlink the old path.
    target = tmp_path / "relief" / "proj-wt__billy"
    target.parent.mkdir()
    shutil.move(str(dest), str(target))
    dest.symlink_to(target)
    return shared, dest, target


def test_gc_refuses_a_relocated_worktree_before_touching_it(tmp_path):
    shared, dest, target = _relocated_worktree(tmp_path)
    before = sorted(p.name for p in target.iterdir())
    with pytest.raises(WorkspaceError) as e:
        cleanup_worktree(shared, "billy", holds_work=lambda d, b: False)
    assert not isinstance(e.value, WorktreeDamage)       # a true refusal
    assert "relocated worktree" in str(e.value)
    assert dest.is_symlink()                              # link untouched
    assert sorted(p.name for p in target.iterdir()) == before   # nothing deleted
    assert (target / "f.txt").read_text() == "tracked\n"


def test_raw_remove_through_a_symlink_is_reported_as_damage_not_refusal(tmp_path):
    # The incident itself: git empties the target and then fails on the link.
    # Whatever git does, the outcome must be worded as DAMAGE.
    shared, dest, target = _relocated_worktree(tmp_path)
    with pytest.raises(WorkspaceError) as e:
        git_worktree_remove(shared, dest)
    # The fixture must actually reproduce the incident (files gone, link left),
    # or this test proves nothing.
    assert dest.is_symlink() and not (target / ".git").exists(), \
        "fixture did not reproduce the partial delete"
    assert isinstance(e.value, WorktreeDamage), str(e.value)
    assert "FAILED PART-WAY" in str(e.value)


def test_ordinary_worktree_is_still_removed(tmp_path):
    # Control: the guard must not break the normal, non-relocated path.
    shared = tmp_path / "proj"
    shared.mkdir()
    _git("init", "-q", "-b", "main", cwd=shared)
    _git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
         "--allow-empty", "-m", "base", cwd=shared)
    dest = tmp_path / "proj-wt" / "billy"
    dest.parent.mkdir()
    _git("worktree", "add", "-q", "-b", "wt/billy", str(dest), "main", cwd=shared)
    assert cleanup_worktree(shared, "billy", holds_work=lambda d, b: False) is True
    assert not dest.exists()
