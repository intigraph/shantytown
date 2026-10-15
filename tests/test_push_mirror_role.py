"""Declared mirrors are never pushed and never prove publication (aegis-x74).

THE LEAK. skein has an internal primary and a public GitHub mirror that only a
scrubbed, squashed sync may advance. Both remotes carried
`st-push-allowed=true`, so a normal `st repo push` of a feature branch wrote the
raw branch to the public mirror. `st-push-allowed` only answers "is this ours?";
nothing could say "never write here".

Every test pairs the remote that must change with the one that must not, so a
build that pushes nothing, or everything, fails here.
"""
from __future__ import annotations

from unittest.mock import Mock

import pytest

from shantytown import cycle, workspace
from shantytown.cli import main, OK, REFUSED
from tests.test_push_every_remote import two_remotes, _git, _commit  # noqa: F401


def _ref(bare, ref):
    import subprocess
    r = subprocess.run(["git", "-C", str(bare), "rev-parse", "--verify", "-q", ref],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def _push(repo, *extra):
    return main(["repo", "push", str(repo), "ellie", "--branch", "ellie/feature",
                 *extra])


def test_declared_mirror_is_skipped_even_when_push_allowed(two_remotes, capsys):
    repo, wt, origin, forge = two_remotes
    _git(repo, "config", "remote.forge.st-push-role", "mirror")
    _commit(wt, "feature")
    head = _git(wt, "rev-parse", "HEAD")
    mirror_main = _ref(forge, "refs/heads/main")

    assert _push(repo) == OK

    assert _ref(origin, "refs/heads/ellie/feature") == head
    assert _ref(forge, "refs/heads/ellie/feature") is None
    assert _ref(forge, "refs/heads/main") == mirror_main
    out = capsys.readouterr().out
    assert "forge: skipped (mirror)" in out
    assert "forge: pushed" not in out
    assert "origin: pushed" in out


def test_mirror_needs_no_push_approval_to_be_skipped(two_remotes):
    repo, wt, origin, forge = two_remotes
    _git(repo, "config", "--unset", "remote.forge.st-push-allowed")
    _git(repo, "config", "remote.forge.st-push-role", "mirror")
    _commit(wt, "feature")
    # Control: the same set without the role is refused as a foreign authority.
    assert workspace.push_authority_refusal(repo) == ""
    outcomes = workspace.push_every_remote(wt, "HEAD", "ellie/feature")
    assert [(o.remote, o.ok, o.skipped) for o in outcomes] == [
        ("forge", True, True), ("origin", True, False)]
    assert _ref(forge, "refs/heads/ellie/feature") is None


def test_unrecognised_role_refuses_before_any_remote(two_remotes, capsys):
    repo, wt, origin, forge = two_remotes
    _git(repo, "config", "remote.forge.st-push-role", "mirorr")
    _commit(wt, "feature")
    push = Mock(side_effect=AssertionError("must not contact a remote"))
    outcomes = workspace.push_every_remote(wt, "HEAD", "ellie/feature",
                                           push_run=push)
    assert len(outcomes) == 1 and not outcomes[0].ok
    assert "forge=mirorr" in outcomes[0].reason
    push.assert_not_called()

    assert _push(repo) == REFUSED
    assert _ref(origin, "refs/heads/ellie/feature") is None
    assert _ref(forge, "refs/heads/ellie/feature") is None
    assert "st-push-role" in capsys.readouterr().err


def test_all_mirror_set_refuses(two_remotes):
    repo, wt, origin, forge = two_remotes
    for r in ("origin", "forge"):
        _git(repo, "config", f"remote.{r}.st-push-role", "mirror")
    _commit(wt, "feature")
    assert _push(repo) == REFUSED
    assert _ref(origin, "refs/heads/ellie/feature") is None
    assert _ref(forge, "refs/heads/ellie/feature") is None
    assert "every configured remote is a declared mirror" in \
        workspace.push_authority_refusal(repo)


def test_peer_role_is_an_explicit_approval(two_remotes):
    repo, wt, origin, forge = two_remotes
    _git(repo, "config", "--unset", "remote.forge.st-push-allowed")
    assert "Unapproved: forge" in workspace.push_authority_refusal(repo)
    _git(repo, "config", "remote.forge.st-push-role", "peer")
    assert workspace.push_authority_refusal(repo) == ""
    _commit(wt, "feature")
    assert _push(repo) == OK
    assert _ref(forge, "refs/heads/ellie/feature") == _git(wt, "rev-parse", "HEAD")


@pytest.mark.parametrize("staleness", [
    # What `st agent cycle` actually passes (cli._cmd_cycle).
    lambda t: workspace.tree_staleness(t, fetch=True, untracked_all=True,
                                       tracked_only=True),
    # The no-fetch read behind the edit-time hook and `st crew`.
    workspace.tree_staleness,
], ids=["cycle-fetch", "local-refs"])
def test_a_mirror_never_proves_publication(two_remotes, staleness):
    repo, wt, origin, forge = two_remotes
    _commit(wt, "preserved")
    branch = _git(wt, "symbolic-ref", "--short", "HEAD")
    # The commit exists ONLY on the second remote.
    _git(wt, "push", "-q", "forge", f"HEAD:refs/heads/{branch}")

    # Control: as a trusted peer it proves publication.
    ok = cycle.assess("worker", [wt], "saved checkpoint", staleness,
                      reachable=lambda _: True)
    assert ok.ok, ok.render()

    _git(repo, "config", "remote.forge.st-push-role", "mirror")
    assert "forge" not in workspace.publication_remotes(wt)
    verdict = cycle.assess("worker", [wt], "saved checkpoint", staleness,
                           reachable=lambda _: True)
    assert not verdict.ok
    assert verdict.risks[0].unpushed == 1
