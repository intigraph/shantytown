"""Real-Git squash GC proofs; all remotes are private local bare repositories."""
import os
import subprocess

import pytest

from shantytown import workspace


def git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], check=True,
                          capture_output=True, text=True, timeout=10).stdout.strip()


@pytest.fixture
def landed(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    remote = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "--initial-branch=main", str(remote)],
                   check=True, capture_output=True, timeout=10)
    shared = tmp_path / "project"
    subprocess.run(["git", "clone", str(remote), str(shared)],
                   check=True, capture_output=True, timeout=10)
    git(shared, "config", "user.name", "Fixture")
    git(shared, "config", "user.email", "fixture@example.invalid")
    (shared / "file").write_text("base")
    git(shared, "add", "file")
    git(shared, "commit", "-m", "base")
    git(shared, "push", "origin", "main")
    dest = workspace.worktree_for(shared, "probe")
    git(shared, "worktree", "add", "-b", "wt/probe", str(dest), "main")
    for value in ("first", "second"):
        (dest / "file").write_text(value)
        git(dest, "commit", "-am", value)
    git(dest, "push", "origin", "HEAD:refs/heads/wt/probe")
    git(shared, "merge", "--squash", "wt/probe")
    git(shared, "commit", "-m", "squashed")
    git(shared, "push", "origin", "main")
    assert git(dest, "rev-list", "--count", "origin/main..HEAD") == "2"
    assert git(dest, "rev-parse", "HEAD^{tree}") == git(shared, "rev-parse", "origin/main^{tree}")
    return shared, dest, remote


def test_squash_landed_removed_and_branch_retained(landed):
    shared, dest, _ = landed
    head = git(dest, "rev-parse", "HEAD")
    assert workspace.cleanup_worktree(shared, "probe")
    assert not dest.exists()
    assert git(shared, "rev-parse", "refs/heads/wt/probe") == head


def test_equal_historical_main_tree_is_enough(landed):
    shared, dest, _ = landed
    (shared / "later").write_text("later main work")
    git(shared, "add", "later")
    git(shared, "commit", "-m", "main advances")
    git(shared, "push", "origin", "main")
    assert git(dest, "rev-parse", "HEAD^{tree}") != git(shared, "rev-parse", "origin/main^{tree}")
    assert workspace.cleanup_worktree(shared, "probe")


@pytest.mark.parametrize("case", ["unlanded", "unpublished", "not-pushed", "remote-moved",
                                  "dirty", "untracked", "detached", "missing-origin", "mode-only", "binary",
                                  "stale-base"])
def test_uncertain_or_unlanded_worktree_kept(landed, case):
    shared, dest, remote = landed
    if case == "unlanded":
        (dest / "file").write_text("not landed")
        git(dest, "commit", "-am", "new work")
        git(dest, "push", "origin", "HEAD:refs/heads/wt/probe")
    elif case in ("mode-only", "binary"):
        if case == "mode-only":
            (dest / "file").chmod(0o755)
        else:
            (dest / "file").write_bytes(b"new\x00binary\xff")
        git(dest, "commit", "-am", "unlanded mode or binary")
        git(dest, "push", "origin", "HEAD:refs/heads/wt/probe")
    elif case == "unpublished":
        git(shared, "push", "origin", ":refs/heads/wt/probe")
    elif case == "not-pushed":
        git(dest, "commit", "--allow-empty", "-m", "unpublished metadata")
    elif case == "remote-moved":
        git(remote, "update-ref", "refs/heads/wt/probe", git(shared, "rev-parse", "main"))
    elif case == "dirty":
        (dest / "file").write_text("dirty")
    elif case == "untracked":
        (dest / "untracked").write_text("keep")
    elif case == "detached":
        git(dest, "checkout", "--detach")
    elif case == "missing-origin":
        git(shared, "remote", "remove", "origin")
    elif case == "stale-base":
        # Change the remote behind the local tracking ref; never assume it fresh.
        git(shared, "commit", "--allow-empty", "-m", "new main metadata")
        git(shared, "push", "origin", "HEAD:refs/heads/future")
        git(remote, "update-ref", "refs/heads/main", git(shared, "rev-parse", "main"))
    assert not workspace.cleanup_worktree(shared, "probe")
    assert dest.exists()


@pytest.mark.parametrize("failure", ["error", "timeout"])
def test_remote_proof_failure_keeps_worktree(landed, monkeypatch, failure):
    shared, dest, _ = landed
    original = workspace._git

    def failed(path, *args, **kwargs):
        if args[0] == "ls-remote":
            if failure == "timeout":
                raise subprocess.TimeoutExpired("private remote fixture", 30)
            return 1, ""
        return original(path, *args, **kwargs)

    monkeypatch.setattr(workspace, "_git", failed)
    assert not workspace.cleanup_worktree(shared, "probe")
    assert dest.exists()
