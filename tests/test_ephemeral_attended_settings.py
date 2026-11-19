"""aegis-e579 option B: attended jobs get exactly their prompt's commands.

Each rule is shown saying NO as well as yes."""
from __future__ import annotations

import json

import pytest

from shantytown import ephemeral as eph


def _rec(tmp_path, **kw):
    rec = {"name": "eph-review-abc123", "job": "review", "harness": "claude",
           "workspace": str(tmp_path / "ws")}
    rec.update(kw)
    (tmp_path / "ws").mkdir(exist_ok=True)
    return rec


def _read(path):
    return json.loads(path.read_text())


def test_attended_claude_review_gets_exact_allowlist_and_denies(tmp_path):
    path = eph.write_attended_settings(_rec(tmp_path), unattended=False)
    assert path == tmp_path / "ws" / ".claude" / "settings.local.json"
    perms = _read(path)["permissions"]
    assert "Bash(st agent spawn --report:*)" in perms["allow"]
    assert "Bash(gh pr comment:*)" in perms["allow"]
    for wide in ("Bash", "Bash(*)", "Bash(gh:*)", "Bash(git:*)", "Edit", "Write"):
        assert wide not in perms["allow"]
    for denied in ("Edit", "Write", "Bash(git push:*)", "Bash(gh pr merge:*)"):
        assert denied in perms["deny"]


def test_merge_job_may_use_the_guarded_merge_but_not_gh_merge(tmp_path):
    perms = _read(eph.write_attended_settings(_rec(tmp_path, job="merge"), unattended=False))["permissions"]
    assert "Bash(st agent spawn --merge:*)" in perms["allow"]
    assert "Bash(gh pr merge:*)" in perms["deny"]
    assert "Bash(gh pr comment:*)" not in perms["allow"]


@pytest.mark.parametrize("kw,unattended", [
    ({}, True),                     # protected UID jobs: operator-staged settings only
    ({"harness": "codex"}, False),  # not a Claude harness
    ({"job": "task"}, False),       # no reviewed allowlist for this kind: unchanged behaviour
    ({"job": "triage"}, False),
])
def test_no_settings_written_outside_attended_claude_review_or_merge(tmp_path, kw, unattended):
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
    assert _read(target) == {"permissions": {"allow": ["Bash"]}}


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
