"""aegis-e579 option B: attended jobs get exactly their prompt's commands,
bound to their own PR, with no file-write or outbound channel.

Each rule is shown saying NO as well as yes."""
from __future__ import annotations

import json

import pytest

from shantytown import ephemeral as eph


def _rec(tmp_path, **kw):
    rec = {"name": "eph-review-abc123", "job": "review", "harness": "claude",
           "repo": "o/n", "pr": 7, "item": "it-1", "workspace": str(tmp_path / "ws")}
    rec.update(kw)
    (tmp_path / "ws").mkdir(exist_ok=True)
    return rec


def _perms(tmp_path, **kw):
    path = eph.write_attended_settings(_rec(tmp_path, **kw), unattended=False)
    return json.loads(path.read_text())["permissions"]


def test_review_rules_are_bound_to_the_exact_pr_and_worktree(tmp_path):
    perms = _perms(tmp_path)
    assert perms["allow"] == [
        "Read(./**)",
        "Bash(gh pr view 7 --repo o/n:*)", "Bash(gh pr checks 7 --repo o/n:*)",
        "Bash(gh pr diff 7 --repo o/n:*)",
        "Bash(st agent spawn --report:*)"]


def test_no_write_or_unbound_read_channel_is_allowed(tmp_path):
    """Ian's findings: git --output writes files; bare Read + a comment exfiltrates."""
    perms = _perms(tmp_path)
    joined = " ".join(perms["allow"])
    assert "git" not in joined
    assert "gh pr comment" not in joined
    for wide in ("Read", "Grep", "Glob", "Bash", "Bash(gh:*)"):
        assert wide not in perms["allow"]
    for denied in ("Bash(git:*)", "Bash(gh pr comment:*)", "Bash(gh api:*)", "Edit", "Write", "WebFetch"):
        assert denied in perms["deny"]


def test_merge_job_may_use_the_guarded_merge_but_not_gh_merge(tmp_path):
    perms = _perms(tmp_path, job="merge", name="eph-merge-abc123")
    assert "Bash(st agent spawn --merge:*)" in perms["allow"]
    assert "Bash(gh pr diff 7 --repo o/n:*)" not in perms["allow"]
    assert "Bash(gh pr merge:*)" in perms["deny"]


@pytest.mark.parametrize("kw,unattended", [
    ({}, True),                       # protected UID jobs: operator-staged settings only
    ({"harness": "codex"}, False),    # not a Claude harness
    ({"job": "task"}, False),         # no reviewed allowlist for this kind
    ({"job": "triage"}, False),
    ({"repo": None}, False),          # nothing to bind to
    ({"repo": "o/n x"}, False),       # a repo that is not a plain owner/name
    ({"pr": "7 --repo evil/x"}, False),
])
def test_no_settings_outside_bindable_attended_claude_review_or_merge(tmp_path, kw, unattended):
    rec = _rec(tmp_path, **kw)
    assert eph.write_attended_settings(rec, unattended=unattended) is None
    assert not (tmp_path / "ws" / ".claude").exists()


def test_existing_different_settings_are_refused_not_widened(tmp_path):
    rec = _rec(tmp_path)
    target = tmp_path / "ws" / ".claude" / "settings.local.json"
    target.parent.mkdir()
    target.write_text('{"permissions": {"allow": ["Bash"]}}\n')
    with pytest.raises(eph.Refused):
        eph.write_attended_settings(rec, unattended=False)
    assert json.loads(target.read_text()) == {"permissions": {"allow": ["Bash"]}}


def test_identical_existing_settings_are_accepted(tmp_path):
    rec = _rec(tmp_path)
    first = eph.write_attended_settings(rec, unattended=False)
    assert eph.write_attended_settings(rec, unattended=False) == first


def test_symlinked_settings_are_refused(tmp_path):
    rec = _rec(tmp_path)
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_text("{}")
    (tmp_path / "ws" / ".claude").mkdir()
    (tmp_path / "ws" / ".claude" / "settings.local.json").symlink_to(elsewhere)
    with pytest.raises(eph.Refused):
        eph.write_attended_settings(rec, unattended=False)
    assert elsewhere.read_text() == "{}"


def test_attended_review_prompt_never_asks_the_job_to_comment(tmp_path):
    rec = dict(_rec(tmp_path), administrator="boss", deadline=1_800_000_000, max_turns=40)
    text = eph.prompt(rec)
    assert "gh pr comment" not in text and "git " not in text
    assert "--summary-file -" in text
    protected = dict(rec, uid_binding={"uid": 10001, "sha256": "0" * 64})
    assert "gh pr comment" in eph.prompt(protected)  # UID jobs keep their reviewed prompt
