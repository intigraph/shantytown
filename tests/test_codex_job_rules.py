"""Attended Codex jobs get the exact per-job allowlist as exec-policy rules,
and a job stuck on an approval prompt ends as blocked (aegis-e579 ruling B)."""
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from shantytown import ephemeral as eph

REC = dict(job="review", repo="intigraph/example", pr=75, harness="codex", name="eph-review-x")
APPROVAL = ("• Working\n\n  Would you like to run the following command?\n\n"
            "  $ gh pr view 76 --repo intigraph/example\n\n"
            "\x1b[1m›\x1b[0m 1. Yes, proceed (y)\n"
            "  2. Yes, and don't ask again for commands that start with `gh pr view` (p)\n"
            "  3. No, and tell Codex what to do differently (esc)\n\n"
            "  Press enter to confirm or esc to cancel\n")
READY = "\x1b[1m›\x1b[0m \x1b[2mAsk Codex to do anything\x1b[0m\n  GPT-6.1 Terra default · /w\n  ? for shortcuts\n"
NUMBERED_OUTPUT = "1. read the diff\n2. checked CI\n" + READY


def test_review_rules_allow_exactly_the_jobs_commands():
    body = eph.codex_job_rules(REC, unattended=False)
    assert '["gh", "pr", ["view", "checks", "diff"], "75", "--repo", "intigraph/example"]' in body
    assert '["st", "agent", "spawn", "--report"], decision="allow"' in body
    assert "--merge" not in body
    for forbidden in ('["git"]', '["gh", "pr", "comment"]', '["gh", "pr", "merge"]', '["gh", "api"]'):
        assert f'pattern={forbidden}, decision="forbidden"' in body


def test_merge_rules_allow_the_guarded_merge_and_no_diff():
    body = eph.codex_job_rules(dict(REC, job="merge"), unattended=False)
    assert '["gh", "pr", ["view", "checks"], "75"' in body
    assert '["st", "agent", "spawn", "--merge"], decision="allow"' in body


@pytest.mark.parametrize("rec,unattended", [
    (dict(REC, harness="claude"), False),
    (REC, True),
    (dict(REC, uid_binding={"uid": 10001}), False),
    (dict(REC, job="triage"), False),
    (dict(REC, repo="bad repo"), False),
    (dict(REC, pr="75; rm"), False),
])
def test_no_rules_outside_the_attended_codex_lane(rec, unattended):
    assert eph.codex_job_rules(rec, unattended=unattended) is None


def test_codex_review_is_attended_so_st_posts_the_comment():
    assert eph.attended_review(REC)
    assert "Do NOT comment on the PR" in eph._JOBS["review_attended"]


def test_rules_written_owner_only_and_never_widened(tmp_path):
    path = eph.write_codex_job_rules(REC, tmp_path, unattended=False)
    assert path == tmp_path / "rules" / eph.CODEX_RULES_FILE
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert eph.write_codex_job_rules(REC, tmp_path, unattended=False) == path
    path.write_text('prefix_rule(pattern=["gh"], decision="allow")\n')
    with pytest.raises(eph.Refused, match="not widening"):
        eph.write_codex_job_rules(REC, tmp_path, unattended=False)


def test_rules_never_written_through_a_symlink(tmp_path):
    real = tmp_path / "elsewhere"
    real.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    (home / "rules").symlink_to(real)
    with pytest.raises(eph.Refused, match="symlink"):
        eph.write_codex_job_rules(REC, home, unattended=False)
    assert not any(real.iterdir())


def _codex():
    found = shutil.which("codex")
    if not found:
        return None
    probe = subprocess.run([found, "execpolicy", "--help"], capture_output=True, text=True)
    return found if probe.returncode == 0 else None


@pytest.mark.skipif(_codex() is None, reason="needs a codex CLI with execpolicy")
@pytest.mark.parametrize("cmd,decision", [
    ("gh pr view 75 --repo intigraph/example --json headRefOid", "allow"),
    ("gh pr diff 75 --repo intigraph/example", "allow"),
    ("st agent spawn --report --verdict approve --head abc --summary-file -", "allow"),
    ("gh pr view 76 --repo intigraph/example", None),
    ("gh pr comment 75 --repo intigraph/example --body x", "forbidden"),
    ("git push origin HEAD", "forbidden"),
])
def test_codex_evaluates_the_rules_as_intended(tmp_path, cmd, decision):
    path = eph.write_codex_job_rules(REC, tmp_path, unattended=False)
    out = subprocess.run([_codex(), "execpolicy", "check", "-r", str(path), *cmd.split()],
                         capture_output=True, text=True, check=True).stdout
    assert json.loads(out).get("decision") == decision


def test_approval_prompt_detection_needs_picker_and_footer():
    assert eph.awaiting_approval(APPROVAL)
    assert not eph.awaiting_approval(READY)
    assert not eph.awaiting_approval(NUMBERED_OUTPUT)
    assert not eph.awaiting_approval("")


def _live(tmp_path, **extra):
    rec = dict(name="eph-review-a1b2c3", state=eph.LIVE, deadline=10_000, spawned_at=0,
               administrator="lead", job="review", item="i", harness="codex", **extra)
    eph.write(tmp_path, rec)
    return rec


def test_unanswered_prompt_ends_blocked_after_the_wait(tmp_path):
    _live(tmp_path)
    ended = []
    end = lambda name, verdict, cause: ended.append((name, verdict, cause))
    kw = dict(pane_alive=lambda _: True, end=end, prompting=lambda _: True, prompt_wait_s=300)
    assert eph.reap(tmp_path, now=1000, **kw) == []
    assert eph.read(tmp_path, "eph-review-a1b2c3")["prompt_since"] == 1000
    assert eph.reap(tmp_path, now=1200, **kw) == [] and not ended
    eph.reap(tmp_path, now=1300, **kw)
    assert ended == [("eph-review-a1b2c3", "blocked", "approval prompt unanswered")]


def test_answered_prompt_resets_the_clock_and_unknown_never_counts(tmp_path):
    _live(tmp_path, prompt_since=1000)
    ended = []
    end = lambda *a: ended.append(a)
    eph.reap(tmp_path, now=1100, pane_alive=lambda _: True, end=end, prompting=lambda _: False)
    assert "prompt_since" not in eph.read(tmp_path, "eph-review-a1b2c3")
    eph.reap(tmp_path, now=1500, pane_alive=lambda _: True, end=end, prompting=lambda _: None)
    assert "prompt_since" not in eph.read(tmp_path, "eph-review-a1b2c3") and not ended


def test_reap_without_a_prompt_reader_is_unchanged(tmp_path):
    _live(tmp_path, prompt_since=0)
    ended = []
    eph.reap(tmp_path, now=5000, pane_alive=lambda _: True, end=lambda *a: ended.append(a))
    assert ended == []
