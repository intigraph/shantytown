"""Run the push handler against two local bare peers, without external protocols."""
import argparse
import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile

source, label = sys.argv[1:]
sys.path.insert(0, source)
from shantytown import cli  # noqa: E402


def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args],
                                   text=True, stderr=subprocess.PIPE).strip()


os.environ["GIT_ALLOW_PROTOCOL"] = "file"
with tempfile.TemporaryDirectory(prefix="push-demo-") as directory:
    root = Path(directory)
    repo = root / "project"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    (repo / "file").write_text("base\n")
    git(repo, "add", "file")
    git(repo, "commit", "-qm", "base")
    peers = [root / "origin.git", root / "peer.git"]
    for name, peer in zip(("origin", "peer"), peers):
        git(root, "init", "-q", "--bare", "-b", "main", str(peer))
        git(repo, "remote", "add", name, str(peer))
        git(repo, "config", f"remote.{name}.st-push-allowed", "true")
        git(repo, "push", "-q", name, "main")
    canonical = root / "project-wt" / "worker"
    extra = root / "extra source"
    git(repo, "worktree", "add", "-qb", "wt/worker", str(canonical))
    git(repo, "worktree", "add", "-qb", "worker/topic", str(extra))
    (extra / "topic").write_text("selected\n")
    git(extra, "add", "topic")
    git(extra, "commit", "-qm", "topic")
    os.environ["GT_ROOT"] = str(root)
    os.environ["WORKSPACE_ROOT"] = str(root / "workspace")
    os.chdir(extra)
    args = argparse.Namespace(repo="project", agent="worker",
                              source_branch="worker/topic",
                              branch="worker/topic", timeout=60)
    output, errors = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
        rc = cli._cmd_push(args)
    print(f"{label}: bare name + explicit topic from extra checkout; rc={rc}")
    print(errors.getvalue().replace(directory, "<fixture>"), end="")
    assert rc == cli.REFUSED
    assert all(git(p, "rev-parse", "main") == git(canonical, "rev-parse", "HEAD")
               for p in peers)
    if label == "AFTER":
        assert "literal worktree path" in errors.getvalue()
    args.repo = str(extra)
    with contextlib.redirect_stdout(io.StringIO()):
        assert cli._cmd_push(args) == cli.OK
    assert all(git(p, "rev-parse", "worker/topic") == git(extra, "rev-parse", "HEAD")
               for p in peers)
    print("CONTROL: explicit extra path pushes exact topic to both local peers; main unchanged")
    os.chdir(source)
