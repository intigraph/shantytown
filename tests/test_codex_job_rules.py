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
    (dict(REC, job="unknown"), False),
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


@pytest.mark.parametrize("job", ["triage", "task"])
def test_non_pr_jobs_get_only_the_guarded_report_command(tmp_path, job):
    rec = dict(job=job, harness="codex", name=f"eph-{job}-a1b2c3")
    path = eph.write_codex_job_rules(rec, tmp_path, unattended=False)
    body = path.read_text()
    assert body.count('decision="allow"') == 1
    assert '["st", "agent", "spawn", "--report"], decision="allow"' in body
    assert 'read its own PR' not in body
    assert '--merge' not in body
    if _codex():
        for cmd, decision in [
            (["st", "agent", "spawn", "--report", "--verdict", "blocked", "--summary-file", "-"], "allow"),
            (["st", "agent", "spawn", "--merge"], None),
            (["gh", "pr", "view", "75", "--repo", "intigraph/example"], None),
            *([(["git", "push"], "forbidden")] if job == "triage" else []),
        ]:
            result = subprocess.run([_codex(), "execpolicy", "check", "-r", str(path), *cmd],
                                    capture_output=True, text=True, check=True)
            assert json.loads(result.stdout).get("decision") == decision


TASK = dict(job="task", harness="codex", name="eph-task-a1b2c3")


@pytest.mark.skipif(_codex() is None, reason="needs a codex CLI with execpolicy")
@pytest.mark.parametrize("cmd,decision", [
    # aegis-za4f D1: a task job commits and pushes ITS OWN branch.
    ("git status", None),
    ("git diff origin/main", None),
    ("git commit -m fix", None),
    ("git push -u origin eph-task-a1b2c3", None),
    # ...but never the base branch, never a rewrite, never a direct merge.
    ("git push origin main", "forbidden"),
    ("git push origin HEAD:main", "forbidden"),
    ("git push --force origin eph-task-a1b2c3", "forbidden"),
    ("git push -f", "forbidden"),
    ("git reset --hard origin/main", "forbidden"),
    ("git rebase main", "forbidden"),
    ("gh pr merge 1 --squash", "forbidden"),
    ("gh api repos/x/y", "forbidden"),
])
def test_task_jobs_get_git_on_their_own_branch_only(tmp_path, cmd, decision):
    path = eph.write_codex_job_rules(TASK, tmp_path, unattended=False)
    out = subprocess.run([_codex(), "execpolicy", "check", "-r", str(path), *cmd.split()],
                         capture_output=True, text=True, check=True).stdout
    assert json.loads(out).get("decision") == decision


def test_task_sandbox_is_network_plus_exact_roots_never_full_access(tmp_path):
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    rec = dict(TASK, worktree_of=str(repo))
    args = eph.codex_job_sandbox(rec, unattended=False, cache_home=tmp_path / "cache")
    assert args[0::2] == ["-c", "-c", "-c"]
    joined = " ".join(args)
    assert 'sandbox_mode="workspace-write"' in joined
    assert "sandbox_workspace_write.network_access=true" in joined
    assert "danger-full-access" not in joined and "approval_policy" not in joined
    roots = json.loads(args[-1].split("=", 1)[1])
    assert roots == [str(tmp_path / "cache" / "shantytown" / "read-budget-v1"),
                     str((repo / ".git").resolve())]


@pytest.mark.parametrize("rec,unattended", [
    (dict(TASK, job="review", repo="a/b", pr=1), False),
    (dict(TASK, job="triage"), False),
    (dict(TASK, harness="claude"), False),
    (TASK, True),
    (dict(TASK, uid_binding={"uid": 10001}), False),
])
def test_only_attended_codex_task_jobs_get_a_sandbox_profile(tmp_path, rec, unattended):
    assert eph.codex_job_sandbox(rec, unattended=unattended, cache_home=tmp_path) is None
    assert eph.write_codex_job_sandbox(rec, tmp_path / "home", unattended=unattended,
                                       cache_home=tmp_path) is None


def test_sandbox_file_round_trips_and_is_never_widened(tmp_path):
    home = tmp_path / "home"
    path = eph.write_codex_job_sandbox(TASK, home, unattended=False, cache_home=tmp_path / "c")
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert (tmp_path / "c" / "shantytown" / "read-budget-v1").is_dir()
    args = eph.codex_daemon_sandbox_args(TASK["name"], home)
    assert args == eph.codex_job_sandbox(TASK, unattended=False, cache_home=tmp_path / "c")
    # Another card never reads it, and a crew name never reads anything.
    with pytest.raises(eph.Refused):
        eph.codex_daemon_sandbox_args("eph-task-ffffff", home)  # the file names another job
    assert eph.codex_daemon_sandbox_args("ellie", home) == []
    # Same content is idempotent; different content refuses.
    assert eph.write_codex_job_sandbox(TASK, home, unattended=False, cache_home=tmp_path / "c") == path
    with pytest.raises(eph.Refused):
        eph.write_codex_job_sandbox(TASK, home, unattended=False, cache_home=tmp_path / "other")


@pytest.mark.parametrize("bad", ['sandbox_mode="danger-full-access"', 'approval_policy="never"',
                                 "sandbox_workspace_write.network_access=true --dangerously-bypass"])
def test_a_tampered_sandbox_file_refuses_rather_than_widens(tmp_path, bad):
    home = tmp_path / "home"
    eph.write_codex_job_sandbox(TASK, home, unattended=False, cache_home=tmp_path)
    path = home / eph.CODEX_SANDBOX_FILE
    data = json.loads(path.read_text())
    data["args"][1] = bad
    path.write_text(json.dumps(data))
    with pytest.raises(eph.Refused):
        eph.codex_daemon_sandbox_args(TASK["name"], home)


def test_a_linked_worktree_job_also_gets_its_own_gitdir_as_a_root(tmp_path):
    """aegis-za4f. MEASURED 2026-11-25 (eph-task-450024): from inside a linked
    worktree Codex keeps <common>/worktrees/<name> read-only even under a
    writable common dir, so `git add` could not create index.lock. The gitdir
    must be named explicitly."""
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-q", "--allow-empty", "-m", "x"], check=True)
    wt = tmp_path / "wt"
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", str(wt)], check=True)
    rec = dict(TASK, worktree_of=str(repo), workspace=str(wt))
    args = eph.codex_job_sandbox(rec, unattended=False, cache_home=tmp_path / "cache")
    roots = json.loads(args[-1].split("=", 1)[1])
    common = str((repo / ".git").resolve())
    assert roots[1] == common
    assert roots[2].startswith(common + "/worktrees/") and len(roots) == 3


OWN = dict(TASK, item="aegis-x1")
OWN_READ = ('prefix_rule(pattern=["st", "work", "item", "show", "aegis-x1"], '
            'decision="allow", justification="st job: read its own item")')


def test_task_job_rules_allow_the_exact_read_of_its_own_item():
    # aegis-kxu: before, the only allow was --report, so the prompt's first
    # command (`st work item show <own item>`) stopped on an approval prompt.
    body = eph.codex_job_rules(OWN, unattended=False)
    assert OWN_READ in body
    assert body.count('decision="allow"') == 2
    assert '"*"' not in body and "aegis-x1*" not in body


@pytest.mark.parametrize("rec", [
    dict(OWN, job="triage"), dict(OWN, job="review", repo="a/b", pr=1),
    dict(OWN, job="merge", repo="a/b", pr=1),
    dict(OWN, item="aegis-*"), dict(OWN, item="aegis-x1 aegis-y2"), dict(OWN, item="$(id)"),
    dict(OWN, item=""), TASK,
])
def test_no_item_read_rule_outside_a_task_job_with_a_literal_item(rec):
    body = eph.codex_job_rules(rec, unattended=False)
    assert "read its own item" not in body and '"show"' not in body


def test_claude_task_job_is_unaffected():
    assert eph.codex_job_rules(dict(OWN, harness="claude"), unattended=False) is None
    assert eph.attended_settings(dict(OWN, harness="claude"), unattended=False) == \
        eph.attended_settings(dict(TASK, harness="claude"), unattended=False)


@pytest.mark.skipif(_codex() is None, reason="needs a codex CLI with execpolicy")
@pytest.mark.parametrize("cmd,decision", [
    ("st work item show aegis-x1", "allow"),
    ("st work item show aegis-x1 --result-json", "allow"),
    ("st work item show aegis-x2", None),
    ("st work item show aegis-x10", None),
    ("st work item show aegis-*", None),
    ("st work item show *", None),
    ("st work item update aegis-x1 --status in_progress", None),
    ("st work item close aegis-x1", None),
    ("st work item comment aegis-x1", None),
    ("st work item aegis-x1 show", None),
])
def test_codex_admits_only_the_own_item_read(tmp_path, cmd, decision):
    path = eph.write_codex_job_rules(OWN, tmp_path, unattended=False)
    out = subprocess.run([_codex(), "execpolicy", "check", "-r", str(path), *cmd.split()],
                         capture_output=True, text=True, check=True).stdout
    assert json.loads(out).get("decision") == decision
