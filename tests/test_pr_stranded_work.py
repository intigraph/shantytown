"""aegis-za4f.15: st repo pr must not strand job work behind an opaque GitHub
failure or st's own provisioning, and a blocked task job pushes its branch."""
import json
import subprocess

import pytest

from shantytown import ephemeral as eph
from shantytown import pr_preflight as p
from shantytown.tooling import BEGIN, END
from test_pr_preflight import BASE, HEAD, REPO, Forge, candidate, create  # noqa: F401
from test_pr_preflight_scratch import World


def gh_fails(monkeypatch, code, stderr):
    calls = []
    def run(argv, *a, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, code, '{"message":"x"}', stderr)
    monkeypatch.setattr(p.subprocess, "run", run)
    return calls


# (a) the failing call is named, with status and redacted stderr

def test_github_failure_names_call_status_and_redacts_stderr(monkeypatch):
    gh_fails(monkeypatch, 1, "gh: Not Found (HTTP 404)\nAuthorization: Bearer ghp_" + "x" * 36)
    with pytest.raises(p.GitHubError) as error:
        p.github(f"repos/{REPO}/commits/feature")
    e = error.value
    assert (e.method, e.status, e.returncode) == ("GET", 404, 1)
    assert f"GET repos/{REPO}/commits/feature" in str(e) and "HTTP 404" in str(e)
    assert "ghp_" not in str(e) and "Bearer" not in str(e)


def test_unauthenticated_gh_reports_exit_without_http_status(monkeypatch):
    gh_fails(monkeypatch, 4, "To get started with GitHub CLI, please run:  gh auth login")
    with pytest.raises(p.GitHubError, match=r"exit 4, HTTP none; stderr: To get started"):
        p.github(f"repos/{REPO}")


def test_command_json_carries_the_failing_call(monkeypatch, capsys, tmp_path):
    from shantytown.cli import build_parser
    gh_fails(monkeypatch, 4, "gh auth login")
    args = build_parser().parse_args(["repo", "pr", REPO, "--bead", "project-new",
                                      "--checkout", str(tmp_path)])
    assert p.command(args) == 2
    out = capsys.readouterr()
    detail = json.loads(out.out)["github"]
    assert detail["call"] == f"gh api --method GET repos/{REPO}" and detail["exit"] == 4
    assert "exit 4" in out.err


def test_unpushed_branch_is_a_push_refusal_not_unverified(tmp_path):
    world = World(tmp_path)
    def api(path, body=None):
        if path.endswith("/commits/feature"):
            raise p.GitHubError("GET", path, 1, 422, "No commit found for SHA: feature")
        return world(path, body)
    with pytest.raises(p.Refused, match="push the exact candidate branch") as error:
        p.candidate(tmp_path, REPO, "main", api)
    assert "unverified" not in str(error.value)


def test_commit_lookup_outage_still_fails_as_github_error(tmp_path):
    world = World(tmp_path)
    def api(path, body=None):
        if path.endswith("/commits/feature"):
            raise p.GitHubError("GET", path, 1, 502, "Bad Gateway")
        return world(path, body)
    with pytest.raises(p.GitHubError, match="HTTP 502"):
        p.candidate(tmp_path, REPO, "main", api)


class FlakyCreate(Forge):
    """POST fails with a 5xx; whether the PR exists afterwards is the variable."""
    def __init__(self, committed, status=502, head=HEAD):
        super().__init__()
        self.committed, self.status, self.pr_head = committed, status, head

    def __call__(self, path, body=None):
        if body is not None:
            self.writes.append(body)
            if self.committed:
                self.rows = [{"number": 99, "state": "open", "title": "New work", "body": "",
                              "draft": False, "changed_files": 1,
                              "html_url": f"https://github.com/{REPO}/pull/99",
                              "head": {"sha": self.pr_head, "ref": "feature",
                                       "repo": {"full_name": REPO}},
                              "base": {"sha": BASE, "ref": "main"},
                              "file_rows": [{"filename": "src/shared.py"}]}]
            raise p.GitHubError("POST", path, 1, self.status, "gh: Server Error")
        return super().__call__(path, body)


def test_5xx_create_then_existing_pr_reads_back_as_created(candidate):
    forge = FlakyCreate(committed=True)
    result = create(forge)
    assert result["created"] == f"https://github.com/{REPO}/pull/99" and result["number"] == 99
    assert len(forge.writes) == 1


def test_5xx_create_without_pr_stays_unknown_and_names_the_call(candidate):
    forge = FlakyCreate(committed=False)
    with pytest.raises(p.Indeterminate, match=r"POST repos/example/project/pulls.*HTTP 502"):
        create(forge)
    assert len(forge.writes) == 1


def test_read_back_of_a_different_head_is_not_created(candidate):
    forge = FlakyCreate(committed=True, head="d" * 40)
    with pytest.raises(p.Indeterminate, match="read-back found no verified PR"):
        create(forge)


def test_4xx_create_rejection_is_a_definite_refusal(candidate):
    forge = FlakyCreate(committed=False, status=422)
    with pytest.raises(p.GitHubError, match="HTTP 422") as error:
        create(forge)
    assert not isinstance(error.value, p.Indeterminate)


# (b) provisioning dirt passes; real source still refuses

def provision(root, *, edit_outside_block=False):
    (root / "AGENTS.md").write_text("# rules\n")
    subprocess.run(["git", "-C", str(root), "add", "AGENTS.md"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "agents"], check=True)
    text = "# rules\n" + ("my real edit\n" if edit_outside_block else "")
    (root / "AGENTS.md").write_text(text + f"\n{BEGIN}\nprojected tooling\n{END}\n")
    for d in (".claude/skills/quipu", ".agents/skills/quipu", ".bobbin/session", ".codex"):
        (root / d).mkdir(parents=True)
        (root / d / "file").write_text("kit")
    (root / ".mcp.json").write_text("{}")
    (root / ".shantytown-tooling.json").write_text("{}")


def test_provisioning_only_dirt_passes_dry_run(tmp_path):
    world = World(tmp_path)
    provision(tmp_path)
    world.head = world.git("rev-parse", "HEAD").decode().strip()
    result = p.run(tmp_path, REPO, "main", "project-scratch", "Body", "Title", [],
                   create=True, dry_run=True, api=world)
    assert result["would_create"] and not world.writes


@pytest.mark.parametrize("dirt", ["source", "outside-block", "staged-kit", "kit-file-is-dir",
                                  "untracked-src"])
def test_real_source_dirt_still_refuses(tmp_path, dirt):
    world = World(tmp_path)
    provision(tmp_path, edit_outside_block=dirt == "outside-block")
    world.head = world.git("rev-parse", "HEAD").decode().strip()
    if dirt == "source":
        (tmp_path / "source.py").write_text("uncommitted\n")
    elif dirt == "staged-kit":
        world.git("add", "AGENTS.md")
    elif dirt == "kit-file-is-dir":
        (tmp_path / ".mcp.json").unlink()
        (tmp_path / ".mcp.json").mkdir()
        (tmp_path / ".mcp.json" / "x").write_text("x")
    elif dirt == "untracked-src":
        (tmp_path / "new_module.py").write_text("x")
    with pytest.raises(p.Refused, match="commit candidate"):
        p.run(tmp_path, REPO, "main", "project-scratch", "Body", "Title", [],
              create=True, dry_run=True, api=world)
    assert not world.writes


# (c) a blocked task job pushes its branch

def job_repo(tmp_path, commit=True):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    ws = tmp_path / "ws"
    def git(*a):
        return subprocess.run(["git", "-C", str(ws), *a], check=True, capture_output=True,
                              text=True).stdout.strip()
    subprocess.run(["git", "clone", "-q", str(remote), str(ws)], check=True, capture_output=True)
    git("config", "user.email", "t@example.org"); git("config", "user.name", "T")
    (ws / "f").write_text("base"); git("add", "f"); git("commit", "-qm", "base")
    git("push", "-q", "origin", "main"); git("fetch", "-q")
    git("checkout", "-qb", "wt/eph-task-abc123")
    if commit:
        (ws / "f").write_text("work"); git("commit", "-qam", "work")
    return remote, ws, git


def test_blocked_task_pushes_its_branch(tmp_path):
    remote, ws, git = job_repo(tmp_path)
    note = eph.push_stranded_work({"job": "task", "name": "eph-task-abc123", "workspace": str(ws)})
    assert note.startswith("pushed wt/eph-task-abc123")
    remote_sha = subprocess.run(["git", "-C", str(remote), "rev-parse", "wt/eph-task-abc123"],
                                capture_output=True, text=True).stdout.strip()
    assert remote_sha == git("rev-parse", "HEAD")


def test_push_failure_says_local_only(tmp_path):
    remote, ws, git = job_repo(tmp_path)
    git("remote", "set-url", "origin", str(tmp_path / "missing.git"))
    note = eph.push_stranded_work({"job": "task", "name": "eph-task-abc123", "workspace": str(ws)})
    assert "NOT pushed" in note and "local-only" in note


@pytest.mark.parametrize("rec", [{"job": "review"}, {"job": "task", "name": "eph-task-other"}])
def test_nothing_pushed_for_other_jobs_or_branches(tmp_path, rec):
    remote, ws, git = job_repo(tmp_path)
    note = eph.push_stranded_work({"name": "eph-task-abc123", **rec, "workspace": str(ws)})
    assert "pushed wt/" not in note
    assert subprocess.run(["git", "-C", str(remote), "rev-parse", "--verify", "-q",
                           "wt/eph-task-abc123"], capture_output=True).returncode != 0


def test_no_commits_means_no_push(tmp_path):
    remote, ws, git = job_repo(tmp_path, commit=False)
    assert eph.push_stranded_work({"job": "task", "name": "eph-task-abc123",
                                   "workspace": str(ws)}) == ""
