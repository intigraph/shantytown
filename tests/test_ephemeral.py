"""st agent spawn --ephemeral (aegis-c01c.2): supervised, administrator-managed
agents for one job. Every supervision rule gets a test that shows it saying NO,
because a check that cannot fail proves nothing (AGENTS.md)."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from shantytown.actor_identity import authenticated_actor as REAL_AUTHENTICATED_ACTOR

from shantytown import cli, config
from shantytown import ephemeral as eph
from shantytown.events import FilesEvents
from shantytown.tmux import NullPanes

NOW = 1_800_000_000.0


def _policy(**kw):
    return config.Ephemeral(**kw)


def _rec(root, **kw):
    job = kw.pop("job", "task")
    req = eph.Request(job=job, item=kw.pop("item", "it-1"),
                      repo=kw.pop("repo", None), pr=kw.pop("pr", None),
                      head=kw.pop("head", "a" * 40 if job == "merge" else None),
                      request_id=kw.pop("request_id", None))
    rec = eph.plan(req, root=root, policy=kw.pop("policy", _policy(max_agents=10)), actor="boss",
                   administrator="boss", host=None, now=kw.pop("now", NOW),
                   role_of=lambda n: "administrator" if n == "boss" else None, name=kw.pop("name", None))
    rec.update(kw)
    eph.write(root, rec)
    return rec


# --- config -------------------------------------------------------------------

def test_config_reads_and_refuses_the_ephemeral_table(tmp_path):
    (tmp_path / "shantytown.toml").write_text(
        "[ephemeral]\nmax_agents = 1\nlifetime_minutes = 30\n"
        "[ephemeral.harness_by_job]\nreview = \"claude\"\n")
    cfg = config.load(tmp_path)
    assert cfg.ephemeral.max_agents == 1 and cfg.ephemeral.lifetime_minutes == 30
    assert cfg.ephemeral.harness_by_job == {"review": "claude"}
    (tmp_path / "shantytown.toml").write_text("[ephemeral]\nmax_agent = 1\n")
    with pytest.raises(config.ConfigError, match="unknown key"):
        config.load(tmp_path)
    (tmp_path / "shantytown.toml").write_text("[ephemeral]\nlifetime_minutes = 0\n")
    with pytest.raises(config.ConfigError, match="lifetime_minutes"):
        config.load(tmp_path)
    (tmp_path / "shantytown.toml").write_text("[ephemeral.harness_by_job]\nreveiw = \"codex\"\n")
    with pytest.raises(config.ConfigError, match="unknown key"):
        config.load(tmp_path)


# --- admission ----------------------------------------------------------------

def test_review_and_merge_need_a_pr_and_jobs_are_closed():
    with pytest.raises(eph.Refused, match="--repo"):
        eph.validate(eph.Request(job="review", item="it-1"))
    with pytest.raises(eph.Refused, match="unknown job"):
        eph.validate(eph.Request(job="deploy", item="it-1"))
    with pytest.raises(eph.Refused, match="owner/name"):
        eph.validate(eph.Request(job="task", item="it-1", repo="../etc"))
    eph.validate(eph.Request(job="review", item="it-1", repo="o/n", pr=3))


def test_reviews_default_to_codex_and_the_rest_to_claude():
    p = _policy()
    assert eph.harness_for(eph.Request("review", "i"), p) == "codex"
    assert eph.harness_for(eph.Request("merge", "i"), p) == "claude"
    assert eph.harness_for(eph.Request("review", "i", harness="claude"), p) == "claude"
    assert eph.harness_for(eph.Request("task", "i"),
                           _policy(harness_by_job={"task": "codex"})) == "codex"


def test_administrator_and_opt_in_verified_authority():
    roles = {"boss": "administrator", "lex": "worker", "lead1": "lead"}.get
    eph.authority(None, roles)  # unmigrated human shell
    with pytest.raises(eph.Refused, match="verified"):
        eph.authority(None, roles, require_verified=True)
    eph.authority("boss", roles)
    for who in ("lex", "lead1"):
        with pytest.raises(eph.Refused, match="administrator"):
            eph.authority(who, roles)
    with pytest.raises(eph.Refused, match="cannot spawn"):
        eph.authority("eph-task-abcdef", lambda n: "administrator")


def test_over_cap_is_refused_not_queued_and_done_jobs_free_the_slot(tmp_path):
    _rec(tmp_path, name="eph-task-000001")
    with pytest.raises(eph.Refused, match="over cap: 1/1"):
        _rec(tmp_path, policy=_policy(max_agents=1))
    with pytest.raises(eph.Refused, match="off"):
        _rec(tmp_path, policy=_policy(max_agents=0))
    rec = eph.read(tmp_path, "eph-task-000001")
    rec["state"] = eph.DONE
    eph.write(tmp_path, rec)
    _rec(tmp_path, policy=_policy(max_agents=1))


def test_no_administrator_means_no_spawn(tmp_path):
    with pytest.raises(eph.Refused, match="no administrator"):
        eph.plan(eph.Request("task", "it-1"), root=tmp_path, policy=_policy(),
                 actor="boss", administrator=None, host=None, now=NOW,
                 role_of=lambda n: "administrator")


def test_merge_lane_is_serialized_and_spaced_per_repo(tmp_path):
    first = _rec(tmp_path, job="merge", repo="o/n", pr=1)
    with pytest.raises(eph.Refused, match="held by " + first["name"]):
        _rec(tmp_path, job="merge", repo="o/n", pr=2)
    _rec(tmp_path, job="merge", repo="o/other", pr=2)          # other repo: own lane
    first.update(state=eph.DONE, ended_at=NOW, result={"verdict": "merged"})
    eph.write(tmp_path, first)
    with pytest.raises(eph.Refused, match="10m apart"):
        _rec(tmp_path, job="merge", repo="o/n", pr=2, now=NOW + 60)
    _rec(tmp_path, job="merge", repo="o/n", pr=2, now=NOW + 601)


# --- the prompt ---------------------------------------------------------------

def test_review_prompt_is_independent_and_never_merges(tmp_path):
    # The agent-posts-its-own-comment template is now the protected-UID lane's;
    # an attended Codex review reports on stdin and st posts (aegis-e579 B).
    text = eph.prompt(_rec(tmp_path, job="review", repo="o/n", pr=7,
                           uid_binding={"uid": 60000, "sha256": "a" * 64}))
    assert "NON-AUTHOR" in text and "gh pr comment 7 --repo o/n" in text
    assert "--head <sha> --evidence <comment-url>" in text
    assert "NEVER push, never merge" in text
    assert "st agent spawn --report --verdict" in text
    attended = eph.prompt(_rec(tmp_path, job="review", repo="o/n", pr=7))
    assert "Do NOT comment on the PR" in attended and "gh pr comment" not in attended


def test_protected_alert_triage_never_inherits_fix_permission(tmp_path):
    rec = _rec(tmp_path, job="triage", item="alert-1",
               uid_binding={"uid": 60000, "sha256": "a" * 64})
    text = eph.prompt(rec)
    assert "READ-ONLY ALERT TRIAGE for alert-1" in text
    assert "A fix goes on your own branch" not in text
    assert "Do NOT ACK or silence alerts, restart services" in text
    assert "write code, create branches or PRs, push, merge" in text
    assert "ORIGINAL item alert-1" in text
    assert "report --verdict blocked" in text
    assert "do not grant capabilities" in text
    assert text.count("st agent spawn --report") == 1


def test_attended_triage_retains_its_existing_fix_scope(tmp_path):
    text = eph.prompt(_rec(tmp_path, job="triage"))
    assert "A fix goes on your own branch" in text
    assert "READ-ONLY ALERT TRIAGE" not in text


def test_merge_prompt_only_through_the_lane_with_the_head_pinned(tmp_path):
    text = eph.prompt(_rec(tmp_path, job="merge", repo="o/n", pr=7))
    assert "SERIALIZED MERGE LANE" in text
    assert "st agent spawn --merge --head" in text and "never `--admin`" in text
    assert "NEVER run `gh pr merge` yourself" in text
    assert "OTHER than the author" in text


# --- bounds -------------------------------------------------------------------

def test_turn_deadline_and_context_budgets_end_the_job(tmp_path):
    rec = _rec(tmp_path, policy=_policy(max_turns=2))
    n = rec["name"]
    assert eph.on_stop(tmp_path, n, 10, NOW) == ""
    assert eph.on_stop(tmp_path, n, 10, NOW) == "turn budget"
    rec = _rec(tmp_path)
    assert eph.on_stop(tmp_path, rec["name"], 999, NOW) == "context budget"
    rec = _rec(tmp_path)
    assert eph.on_stop(tmp_path, rec["name"], 1, rec["deadline"]) == "timeout"


def test_stop_hook_warns_once_then_ends(tmp_path, capsys):
    from shantytown.stop_event import _ephemeral_bounds
    rec = _rec(tmp_path, policy=_policy(max_turns=1))
    ended = []
    end = lambda *args: ended.append(args)
    assert _ephemeral_bounds(tmp_path, rec["name"], None, NOW, end=end) == "warned"
    assert '"decision": "block"' in capsys.readouterr().out and not ended
    assert _ephemeral_bounds(tmp_path, rec["name"], None, NOW, end=end) == "ended"
    assert ended and ended[0][0] == rec["name"] and ended[0][3] == "turn budget"
    assert _ephemeral_bounds(tmp_path, "lex", None, NOW, end=end) is None


# --- ending -------------------------------------------------------------------

def test_the_first_result_wins(tmp_path):
    rec = _rec(tmp_path)
    eph.record_result(tmp_path, rec["name"], "approve", "lgtm", "report", NOW)
    again = eph.record_result(tmp_path, rec["name"], "failed", "", "timeout", NOW + 5)
    assert again["result"]["verdict"] == "approve"


def test_report_reaches_the_administrator_even_when_the_comment_fails(tmp_path):
    rec = _rec(tmp_path, job="review", repo="o/n", pr=4)
    eph.record_result(tmp_path, rec["name"], "request-changes", "1. bug", "report", NOW)
    events = FilesEvents(tmp_path / "events")

    def broken(item, body):
        raise RuntimeError("tracker down")
    problems = eph.notify(eph.read(tmp_path, rec["name"]),
                          persist_event=events.persist, comment=broken)
    assert problems and "item comment NOT written" in problems[0]
    got = events.pending("boss")
    assert len(got) == 1 and got[0].frm == rec["name"] and "REQUEST-CHANGES" in got[0].detail
    # Keyed: a retried notify never sends the administrator a second event.
    eph.notify(eph.read(tmp_path, rec["name"]), persist_event=events.persist,
               comment=lambda *a: None)
    assert len(events.pending("boss")) == 1


def test_teardown_removes_the_card_before_the_pane(tmp_path):
    rec = _rec(tmp_path)
    scratch = eph.ledger_dir(tmp_path) / "scratch" / rec["name"]
    scratch.mkdir(parents=True)
    rec["workspace"] = str(scratch)
    eph.write(tmp_path, rec)
    card = tmp_path / "crew" / f"{rec['name']}.json"
    card.parent.mkdir()
    card.write_text("{}")
    order = []

    def kill(session):
        order.append(("kill", session, card.exists()))
    done = eph.teardown(tmp_path, rec["name"], kill_session=kill)
    assert order == [("kill", f"st-{rec['name']}", False)]
    assert done["state"] == eph.DONE and done["workspace_teardown"] == "removed"
    assert not scratch.exists()


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_a_worktree_with_output_is_kept_and_kit_files_are_not_output(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    _git("init", "-q", cwd=repo)
    _git("-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "--allow-empty",
         "-m", "x", cwd=repo)
    _git("update-ref", "refs/remotes/origin/main", "HEAD", cwd=repo)
    (repo / ".mcp.json").write_text("{}")
    (repo / ".claude").mkdir()
    (repo / ".claude" / "x").write_text("")
    assert eph.worktree_holds_work(repo) is False
    (repo / "notes.txt").write_text("the agent's output")
    assert eph.worktree_holds_work(repo) is True
    (repo / "notes.txt").unlink()
    _git("-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "--allow-empty",
         "-m", "y", cwd=repo)
    assert eph.worktree_holds_work(repo) is True


def test_reaper_ends_dead_and_expired_jobs_and_leaves_healthy_ones(tmp_path):
    dead = _rec(tmp_path, state=eph.LIVE)
    old = _rec(tmp_path, state=eph.LIVE)
    fine = _rec(tmp_path, state=eph.LIVE)
    old["deadline"] = NOW - 1
    eph.write(tmp_path, old)
    alive = {f"st-{old['name']}", f"st-{fine['name']}"}
    ended = []
    lines = eph.reap(tmp_path, pane_alive=alive.__contains__,
                     end=lambda *a: ended.append(a), now=NOW)
    assert sorted(ended) == sorted([(dead["name"], "failed", "died"),
                                    (old["name"], "failed", "timeout")])
    assert len(lines) == 2
    assert eph.reap(tmp_path, pane_alive=lambda s: False, end=lambda *a: 1 / 0,
                    now=NOW, dry_run=True)        # dry run reports, ends nothing


def test_ephemeral_names_are_never_board_capacity():
    assert eph.is_ephemeral_name("eph-review-1a2b3c")
    assert not eph.is_ephemeral_name("lex")
    assert not eph.is_ephemeral_name("eph-review-../x")


# --- the command --------------------------------------------------------------

def test_spawn_repo_flag_does_not_clobber_the_tracker_store():
    a = cli._parse_args(["--repo", "/store", "agent", "spawn", "--ephemeral", "--job",
                         "review", "--item", "it-1", "--repo", "o/n", "--pr", "3"])
    assert a.cmd == "spawn" and a.repo == "/store" and a.pr_repo == "o/n" and a.pr == 3


@pytest.fixture
def store(tmp_path, monkeypatch):
    root = tmp_path / ".shanty"
    (root / "crew").mkdir(parents=True)
    (root / "crew" / "boss.json").write_text(json.dumps(
        {"role": "administrator", "pane": "st-boss", "dangerous": True}))
    (root / "shantytown.toml").write_text("[ephemeral]\nmax_agents = 1\nunattended = false\nrequire_verified_identity = true\n")
    panes = NullPanes(live=set())
    monkeypatch.setattr(cli, "_panes", lambda a: panes)
    from shantytown import actor_identity
    panes.verified_actor = 'boss'
    def authenticated():
        principal = panes.verified_actor
        claimed = os.environ.get('SHANTY_AGENT')
        if principal and claimed and principal != claimed:
            raise actor_identity.IdentityError('SHANTY_AGENT differs from authenticated principal')
        return principal
    monkeypatch.setattr(actor_identity, 'authenticated_actor', authenticated)
    launched = []

    behaviour = {"rc": cli.OK, "delivered": True, "during": None}

    def fake_launch(a, card, panes_, runtime, **kw):
        launched.append(card)
        if behaviour["during"]:
            behaviour["during"](a)
        panes.new_session(card.pane)
        a._startup_delivered = behaviour["delivered"]
        return behaviour["rc"]
    panes.behaviour = behaviour
    monkeypatch.setattr(cli, "_launch", fake_launch)
    monkeypatch.setattr(cli, "_runtime", lambda a, p: None)
    monkeypatch.delenv("SHANTY_AGENT", raising=False)
    monkeypatch.setenv("GT_ROOT", str(tmp_path / "gt"))
    return root, panes, launched


def _st(root, *args):
    return cli.main(["--root", str(root), "agent", "spawn", *args])


def test_spawn_launches_a_supervised_card_then_refuses_over_cap(store, capsys):
    root, panes, launched = store
    assert _st(root, "--ephemeral", "--job", "task", "--item", "it-1") == cli.OK
    (rec,) = eph.records(root)
    card = json.loads((root / "crew" / f"{rec['name']}.json").read_text())
    assert card["reports_to"] == "boss" and card["roles"] == ["worker", "first"]
    assert card["dangerous"] is False and card["harness"] == "claude"
    assert launched[0].name == rec["name"]
    assert Path(rec["workspace"]).is_dir()
    assert _st(root, "--ephemeral", "--job", "task", "--item", "it-2") == cli.REFUSED
    assert "over cap" in capsys.readouterr().err
    assert len(launched) == 1


def test_a_worker_cannot_spawn(store, monkeypatch, capsys):
    root, _panes, launched = store
    (root / "crew" / "lex.json").write_text(json.dumps({"role": "worker"}))
    _panes.verified_actor = "lex"
    monkeypatch.setenv("SHANTY_AGENT", "lex")
    assert _st(root, "--ephemeral", "--job", "task", "--item", "it-1") == cli.REFUSED
    assert "not the administrator" in capsys.readouterr().err and not launched


def test_administrator_stop_reports_and_tears_down_and_retry_respawns(store, capsys):
    root, panes, launched = store
    assert _st(root, "--ephemeral", "--job", "task", "--item", "it-1") == cli.OK
    (rec,) = eph.records(root)
    name = rec["name"]
    assert _st(root, "--stop", name) == cli.OK
    done = eph.read(root, name)
    assert done["state"] == eph.DONE and done["result"]["cause"] == "stopped"
    assert not (root / "crew" / f"{name}.json").exists()
    assert not panes.exists(f"st-{name}")
    events = FilesEvents(root / "events").pending("boss")
    assert [e.frm for e in events] == [name]
    assert _st(root, "--retry", name) == cli.OK
    retried = [r for r in eph.records(root) if r.get("retry_of") == name]
    assert len(retried) == 1 and retried[0]["attempt"] == 2 and len(launched) == 2


def test_report_is_only_for_the_ephemeral_agent_itself(store, monkeypatch, capsys):
    root, _panes, _launched = store
    monkeypatch.setenv("SHANTY_AGENT", "boss")
    assert _st(root, "--report", "--verdict", "done") == cli.REFUSED
    assert "verified job" in capsys.readouterr().err


def test_governor_admission_fails_closed_for_ephemeral_work(store, monkeypatch, capsys):
    root, _panes, launched = store

    def blind(a):
        raise OSError("usage reader gone")
    monkeypatch.setattr(cli, "_governors", blind)
    assert _st(root, "--ephemeral", "--job", "task", "--item", "it-1") == cli.REFUSED
    assert "governor admission could not be established" in capsys.readouterr().err
    assert not launched and eph.records(root) == []


# --- review round 1 (hammond, #406) --------------------------------------------

def test_unverifiable_hooks_still_deliver_and_spawn_succeeds(store, capsys):
    """macOS: hook verification is CANNOT_TELL on every launch (no /proc). The
    job was delivered, so the spawn is a success and the job goes LIVE."""
    root, panes, _launched = store
    panes.behaviour.update(rc=cli.CANNOT_TELL, delivered=True)
    assert _st(root, "--ephemeral", "--job", "task", "--item", "it-1") == cli.OK
    (rec,) = eph.records(root)
    assert rec["state"] == eph.LIVE


def test_an_undelivered_job_is_ended_not_left_idle(store, capsys):
    root, panes, _launched = store
    panes.behaviour.update(rc=cli.CANNOT_TELL, delivered=False)
    assert _st(root, "--ephemeral", "--job", "task", "--item", "it-1") == cli.CANNOT_TELL
    (rec,) = eph.records(root)
    assert rec["state"] == eph.DONE and rec["result"]["cause"] == "launch failed"
    assert not panes.exists(f"st-{rec['name']}")
    assert not (root / "crew" / f"{rec['name']}.json").exists()


def test_tend_during_launch_does_not_orphan_the_pane(store):
    """The race: a reap between "ledger + card written" and "pane up" used to
    mark the job died and drop its card, then the pane came up unsupervised."""
    root, panes, _launched = store
    panes.behaviour["during"] = lambda a: cli._spawn_reap(a)
    assert _st(root, "--ephemeral", "--job", "task", "--item", "it-1") == cli.OK
    (rec,) = eph.records(root)
    assert rec["state"] == eph.LIVE and rec["result"] is None
    assert (root / "crew" / f"{rec['name']}.json").exists()
    assert eph.on_stop(root, rec["name"], 1, rec["deadline"] + 1) == "timeout"


def test_a_launching_job_with_no_pane_is_reaped_after_the_grace(tmp_path):
    rec = _rec(tmp_path)
    ended = []
    assert eph.reap(tmp_path, pane_alive=lambda s: False,
                    end=lambda *a: ended.append(a), now=NOW + 10) == []
    eph.reap(tmp_path, pane_alive=lambda s: False, end=lambda *a: ended.append(a),
             now=NOW + eph.LAUNCH_GRACE_S + 1)
    assert ended == [(rec["name"], "failed", "died")]


def test_tend_never_respawns_an_ephemeral_card_it_reaps_it(tmp_path, monkeypatch):
    from tests.test_tend import _Args, _Panes, _Runtime, _roster
    name = "eph-task-abc123"
    root = _roster(tmp_path, {
        "ellie": {"role": "worker", "pane": "p-ellie"},
        name: {"role": "worker", "roles": ["worker", "first"], "pane": f"st-{name}",
               "reports_to": "boss"},
    })
    _rec(root, name=name, now=NOW, state=eph.LIVE)
    panes, runtime = _Panes(live=set()), _Runtime()
    monkeypatch.setattr(cli, "Tmux", lambda *_a, **_k: panes)
    monkeypatch.setattr(cli, "_runtime", lambda a, p: runtime)
    cli._tend_once(_Args(root, backend="files"))
    started = [n for n, _p in runtime.started]
    assert "ellie" in started
    assert name not in started and not panes.exists(f"st-{name}")
    done = eph.read(root, name)
    assert done["state"] == eph.DONE and done["result"]["cause"] == "died"
    assert not (root / "crew" / f"{name}.json").exists()
    assert [e.frm for e in FilesEvents(root / "events").pending("boss")] == [name]


def test_tend_reaps_even_when_it_returns_early(tmp_path, monkeypatch):
    from tests.test_tend import _Args
    rec = _rec(tmp_path, state=eph.LIVE, deadline=1.0)        # long past, by the real clock
    (tmp_path / "crew").mkdir(exist_ok=True)
    monkeypatch.setattr(cli, "_window_launch_gate", lambda a: cli.REFUSED)
    monkeypatch.setattr(cli, "_panes", lambda a: NullPanes(live={f"st-{rec['name']}"}))
    assert cli._tend_once(_Args(tmp_path, backend="files")) == cli.REFUSED
    assert eph.read(tmp_path, rec["name"])["result"]["cause"] == "timeout"


def test_an_ephemeral_process_without_shanty_agent_is_still_that_job(tmp_path):
    rec = _rec(tmp_path, workspace=str(tmp_path / "ws"))
    (tmp_path / "ws" / "sub").mkdir(parents=True)
    by_cwd = eph.inside_ephemeral(tmp_path, cwd=tmp_path / "ws" / "sub", ancestors=[9],
                                  pane_pid=lambda s: None)
    by_tree = eph.inside_ephemeral(tmp_path, cwd=tmp_path, ancestors=[9, 4242, 1],
                                   pane_pid=lambda s: 4242)
    elsewhere = eph.inside_ephemeral(tmp_path, cwd=tmp_path, ancestors=[9, 7],
                                     pane_pid=lambda s: 4242)
    assert by_cwd == by_tree == rec["name"] and elsewhere is None


def test_spawn_from_inside_a_job_is_refused_even_with_the_env_unset(store, monkeypatch, capsys):
    root, _panes, launched = store
    assert _st(root, "--ephemeral", "--job", "task", "--item", "it-1") == cli.OK
    (rec,) = eph.records(root)
    monkeypatch.chdir(rec["workspace"])
    assert _st(root, "--ephemeral", "--job", "task", "--item", "it-2") == cli.REFUSED
    assert "cannot spawn" in capsys.readouterr().err and len(launched) == 1


HEAD = "a" * 40


def _pr(**kw):
    pr = {"head": {"sha": HEAD}, "state": "open", "merged": False, "draft": False,
          "author_association": "MEMBER", "user": {"login": "author"}}
    pr.update(kw)
    return pr


GOOD_REVIEW = [{"user": {"login": "rev"}, "state": "APPROVED", "commit_id": HEAD}]
GREEN = [{"name": "ci", "status": "completed", "conclusion": "success"}]


def test_merge_gate_says_no_to_each_unsafe_merge():
    merge = {"name": "eph-merge-aaaaaa", "job": "merge", "state": eph.LIVE}
    assert eph.merge_gate(merge, HEAD, _pr(), GOOD_REVIEW, GREEN) == ""
    cases = {
        "only a merge job": ({"name": "eph-review-aaaaaa", "job": "review",
                              "state": eph.LIVE}, HEAD, _pr(), GOOD_REVIEW, GREEN),
        "no longer live": (dict(merge, state=eph.DONE), HEAD, _pr(), GOOD_REVIEW, GREEN),
        "head moved": (merge, "b" * 40, _pr(), GOOD_REVIEW, GREEN),
        "outside contribution": (merge, HEAD, _pr(author_association="CONTRIBUTOR"),
                                 GOOD_REVIEW, GREEN),
        "draft": (merge, HEAD, _pr(draft=True), GOOD_REVIEW, GREEN),
        "non-author APPROVE": (merge, HEAD, _pr(), [dict(GOOD_REVIEW[0],
                               user={"login": "author"})], GREEN),
        "requests changes": (merge, HEAD, _pr(), GOOD_REVIEW + [
            {"user": {"login": "x"}, "state": "CHANGES_REQUESTED", "commit_id": HEAD}], GREEN),
        "on the current head": (merge, HEAD, _pr(), [dict(GOOD_REVIEW[0], commit_id="c" * 40)],
                           GREEN),
        "not green": (merge, HEAD, _pr(), GOOD_REVIEW,
                      [{"name": "ci", "status": "completed", "conclusion": "failure"}]),
        "unproven": (merge, HEAD, _pr(), GOOD_REVIEW, []),
    }
    for want, args in cases.items():
        assert want in eph.merge_gate(*args), want


def test_guarded_merge_refuses_a_review_job_and_merges_only_when_the_gate_passes(
        store, monkeypatch, capsys):
    root, _panes, _launched = store
    rec = _rec(root, job="merge", repo="o/n", pr=5, state=eph.LIVE)
    monkeypatch.setenv("SHANTY_AGENT", rec["name"])
    reads = {"repos/o/n/pulls/5": _pr(), "repos/o/n/pulls/5/reviews?per_page=100": GOOD_REVIEW,
             f"repos/o/n/commits/{HEAD}/check-runs?per_page=100": {"check_runs": GREEN}}
    ran = []

    class _R:
        returncode, stdout, stderr = 0, "", ""
    a = cli._parse_args(["--root", str(root), "agent", "spawn", "--merge", "--head", HEAD])
    a.root = root
    assert cli._spawn_merge(a, rec["name"], gh=lambda path: reads[path],
                            run=lambda argv, **k: ran.append(argv) or _R()) == cli.OK
    assert ran == [["gh", "pr", "merge", "5", "--repo", "o/n", "--squash",
                    "--match-head-commit", HEAD]]
    review = _rec(root, job="review", repo="o/n", pr=5, state=eph.LIVE)
    with pytest.raises(eph.Refused, match="only a merge job"):
        cli._spawn_merge(a, review["name"], gh=lambda p: 1 / 0, run=lambda *a, **k: 1 / 0)


def test_a_job_result_reaches_the_administrator_as_a_result_not_a_stop():
    """Measured 10/28: the admin's drain said "re-dispatch eph-review-* — STOPPED"."""
    from shantytown.events import StopEvent
    from shantytown.stop_event import _compose_reason
    from shantytown.tier import is_governance
    ev = StopEvent(id="ev-1", to="boss", frm="eph-review-2a63ff", reason=eph.RESULT_REASON,
                   item="aegis-c01c.2", detail="[ephemeral review o/n#4] APPROVE", ts=NOW)
    assert is_governance(ev.reason)
    text = _compose_reason([ev], {}, NOW + 5)
    assert "FINISHED jobs" in text and "aegis-c01c.2" in text and "APPROVE" in text
    assert "stopped" not in text.lower().replace("not crew", "")


def test_an_ephemeral_turn_boundary_sends_no_crew_stop_event(tmp_path):
    from shantytown.files import FilesRegistry
    from shantytown.stop_event import _send
    rec = _rec(tmp_path, state=eph.LIVE)
    (tmp_path / "crew").mkdir()
    (tmp_path / "crew" / f"{rec['name']}.json").write_text(json.dumps(
        {"role": "worker", "reports_to": "boss", "pane": f"st-{rec['name']}"}))
    (tmp_path / "crew" / "boss.json").write_text(json.dumps({"role": "administrator"}))
    events = FilesEvents(tmp_path / "events")
    assert _send(FilesRegistry(tmp_path / "crew"), events, NullPanes(), rec["name"],
                 tmp_path) == 0
    assert events.pending("boss") == []
    assert eph.read(tmp_path, rec["name"])["turns"] == 1


def test_report_requires_the_verified_job_principal_not_just_the_env(store, monkeypatch, capsys):
    """Live review finding: a crew pane exporting SHANTY_AGENT=<job> could forge
    that job's verdict. Reporting requires the verified job principal."""
    root, panes, _launched = store
    assert _st(root, "--ephemeral", "--job", "task", "--item", "it-1") == cli.OK
    (rec,) = eph.records(root)
    monkeypatch.setenv("SHANTY_AGENT", rec["name"])
    assert _st(root, "--report", "--verdict", "done") == cli.REFUSED   # wrong verified principal
    assert "authenticated principal" in capsys.readouterr().err
    panes.verified_actor = rec["name"]
    monkeypatch.chdir(rec["workspace"])
    monkeypatch.setattr(eph, "detached_teardown", lambda root_, name: None)
    assert _st(root, "--report", "--verdict", "done", "--summary", "ok") in (cli.OK, cli.CANNOT_TELL)
    assert eph.read(root, rec["name"])["result"]["verdict"] == "done"


def test_a_spawn_never_rewrites_the_shared_role_settings(tmp_path):
    from shantytown.protocols import Agent
    from shantytown.provision import _refresh_failure_hook
    shared = tmp_path / "worker.settings.json"
    shared.write_text('{"hooks": {"StopFailure": []}}')
    before = shared.read_text()
    _refresh_failure_hook(Agent(name="eph-task-abcdef", harness="claude"), tmp_path, shared)
    assert shared.read_text() == before
    _refresh_failure_hook(Agent(name="lex", harness="claude"), tmp_path, shared)
    assert shared.read_text() != before        # control: crew launches still repair it


# A scratch-launched job can provision several repository trees during its turn.
def _job_tree(root, name, label):
    repo = root / label
    repo.mkdir()
    _git('init', '-q', cwd=repo)
    (repo / 'tracked.txt').write_text('base\n')
    _git('add', '.', cwd=repo)
    _git('-c', 'user.email=test@example.org', '-c', 'user.name=Test',
         'commit', '-qm', 'base', cwd=repo)
    _git('update-ref', 'refs/remotes/origin/main', 'HEAD', cwd=repo)

    def create(shared, agent):
        from shantytown.workspace import worktree_for
        dest = worktree_for(shared, agent)
        # The receipt exists before Git runs, including when Git is interrupted.
        assert any(e['workspace'] == str(dest.absolute())
                   for e in eph.read(root, name)['worktrees'])
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            _git('worktree', 'add', '-q', '-b', f'wt/{agent}', str(dest),
                 'origin/main', cwd=shared)
        return str(dest)

    tree = Path(eph.provision_worktree(root, name, repo, ensure=create))
    eph.provision_worktree(root, name, repo, ensure=create)  # idempotent receipt
    return repo, tree


def test_teardown_collects_multiple_job_created_trees_and_keeps_output(tmp_path):
    rec = _rec(tmp_path, name='eph-task-abcdef', state=eph.LIVE)
    scratch = eph.ledger_dir(tmp_path) / 'scratch' / rec['name']
    scratch.mkdir(parents=True)
    rec['workspace'] = str(scratch)
    eph.write(tmp_path, rec)
    _, clean = _job_tree(tmp_path, rec['name'], 'clean')
    _, dirty = _job_tree(tmp_path, rec['name'], 'dirty')
    (clean / '.mcp.json').write_text('{}')  # launcher kit alone is removable
    (dirty / 'tracked.txt').write_text('output\n')
    assert len(eph.read(tmp_path, rec['name'])['worktrees']) == 2
    # A destination recorded during pane termination must survive the stale
    # record that teardown read before calling kill_session.
    late = []
    def kill(_):
        late.append(_job_tree(tmp_path, rec['name'], 'late')[1])
    done = eph.teardown(tmp_path, rec['name'], kill_session=kill)
    assert not scratch.exists() and not clean.exists() and not late[0].exists()
    assert (dirty / 'tracked.txt').read_text() == 'output\n'
    outcomes = {e['workspace']: e['result'] for e in done['worktree_teardowns']}
    assert outcomes[str(clean)] == outcomes[str(late[0])] == 'removed'
    assert outcomes[str(dirty)].startswith('kept (holds work)')
    assert eph.read(tmp_path, rec['name']) == done


@pytest.mark.parametrize('output', ['untracked', 'commit', 'branch', 'git-error'])
def test_job_tree_cleanup_preserves_output_and_uncertainty(tmp_path, output):
    rec = _rec(tmp_path, name='eph-task-abcdef', state=eph.LIVE)
    repo, tree = _job_tree(tmp_path, rec['name'], 'project')
    if output == 'untracked':
        (tree / 'notes.txt').write_text('keep this')
    elif output == 'commit':
        _git('-c', 'user.email=test@example.org', '-c', 'user.name=Test',
             'commit', '-q', '--allow-empty', '-m', 'output', cwd=tree)
    elif output == 'branch':
        _git('switch', '-qc', 'published-work', cwd=tree)
    else:
        _git('update-ref', '-d', 'refs/remotes/origin/main', cwd=repo)
    done = eph.teardown(tmp_path, rec['name'], kill_session=lambda _: None)
    assert tree.is_dir()
    assert done['worktree_teardowns'][0]['result'].startswith('kept (')
    assert len(subprocess.run(['git', '-C', str(repo), 'worktree', 'list', '--porcelain'],
                             check=True, capture_output=True, text=True).stdout.split('worktree ')) == 3


def test_recorded_provision_survives_failure_and_result_updates(tmp_path):
    from shantytown.workspace import WorkspaceError
    rec = _rec(tmp_path, name='eph-task-abcdef', state=eph.LIVE)
    def interrupted(repo, name):
        assert len(eph.read(tmp_path, name)['worktrees']) == 1
        raise WorkspaceError('interrupted')
    with pytest.raises(WorkspaceError, match='interrupted'):
        eph.provision_worktree(tmp_path, rec['name'], tmp_path / 'project', ensure=interrupted)
    eph.on_stop(tmp_path, rec['name'], None, NOW)
    assert len(eph.read(tmp_path, rec['name'])['worktrees']) == 1
    done = eph.teardown(tmp_path, rec['name'], kill_session=lambda _: None)
    assert done['worktree_teardowns'][0]['result'] == 'none'
    with pytest.raises(WorkspaceError, match='no active'):
        eph.provision_worktree(tmp_path, rec['name'], tmp_path / 'project', ensure=interrupted)


def test_persistent_provision_does_not_create_ephemeral_ledger(tmp_path):
    assert eph.provision_worktree(tmp_path, 'worker', tmp_path / 'repo',
                                 ensure=lambda repo, name: 'tree') == 'tree'
    assert not eph.ledger_dir(tmp_path).exists()


def test_repo_worktree_command_records_for_the_target_job(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace
    rec = _rec(tmp_path, name='eph-task-abcdef', state=eph.LIVE)
    dest = tmp_path / 'project-wt' / rec['name']
    dest.mkdir(parents=True)
    monkeypatch.setattr(cli, '_resolve_repo', lambda _: tmp_path / 'project')
    monkeypatch.setattr(cli, 'ensure_worktree', lambda repo, name: str(dest))
    monkeypatch.setattr(cli, '_check_worktree_resume', lambda *a, **kw: None)
    monkeypatch.setattr(cli.guard_mod, 'install', lambda _: (False, ''))
    monkeypatch.setattr(cli, '_refresh_worktree', lambda _: 'not refreshed in test')
    args = SimpleNamespace(root=tmp_path, agent=rec['name'], repo='project', gc=False)
    assert cli._cmd_worktree(args) == cli.OK
    [entry] = eph.read(tmp_path, rec['name'])['worktrees']
    assert entry['workspace'] == str(dest)


def test_teardown_keeps_git_errors_and_never_sweeps_other_agents(tmp_path):
    rec = _rec(tmp_path, name='eph-task-abcdef', state=eph.LIVE)
    repo, tree = _job_tree(tmp_path, rec['name'], 'project')
    foreign = tmp_path / 'project-wt' / 'other-worker'
    _git('worktree', 'add', '-q', '-b', 'wt/other-worker', str(foreign),
         'origin/main', cwd=repo)
    def unreadable(*args, **kw):
        raise OSError('git unavailable')
    done = eph.teardown(tmp_path, rec['name'], kill_session=lambda _: None, git=unreadable)
    assert tree.exists() and foreign.exists()
    assert done['worktree_teardowns'][0]['result'].startswith('kept (cleanup uncertain:')
    assert len(done['worktree_teardowns']) == 1


def test_missing_job_identity_cannot_acquire_a_worktree_receipt(tmp_path):
    from shantytown.workspace import WorkspaceError
    called = []
    with pytest.raises(WorkspaceError, match='no active'):
        eph.provision_worktree(tmp_path, 'eph-task-abcdef', tmp_path / 'repo',
                               ensure=lambda *a: called.append(a))
    assert not called and eph.records(tmp_path) == []


def test_spawn_tree_recorded_again_is_only_cleaned_once(tmp_path):
    rec = _rec(tmp_path, name='eph-task-abcdef', state=eph.LIVE)
    repo, tree = _job_tree(tmp_path, rec['name'], 'project')
    latest = eph.read(tmp_path, rec['name'])
    latest.update(workspace=str(tree), worktree_of=str(repo))
    eph.write(tmp_path, latest)
    done = eph.teardown(tmp_path, rec['name'], kill_session=lambda _: None)
    assert done['workspace_teardown'] == 'removed'
    assert done['worktree_teardowns'] == [] and not tree.exists()


def test_ending_job_cannot_provision_another_tree(tmp_path):
    from shantytown.workspace import WorkspaceError
    rec = _rec(tmp_path, name='eph-task-abcdef', state=eph.ENDING)
    with pytest.raises(WorkspaceError, match='no active'):
        eph.provision_worktree(tmp_path, rec['name'], tmp_path / 'repo',
                               ensure=lambda *a: pytest.fail('must not provision'))
    assert 'worktrees' not in eph.read(tmp_path, rec['name'])


@pytest.mark.parametrize('args', [
    ('--ephemeral', '--job', 'task', '--item', 'it-new'),
    ('--report', '--verdict', 'done'),
    ('--merge', '--head', HEAD),
    ('--stop', 'JOB'),
    ('--retry', 'JOB'),
    ('--reap',),
])
@pytest.mark.parametrize('claimed', [None, 'boss'])
def test_guarded_mutations_refuse_unverified_identity_without_side_effects(
        store, monkeypatch, capsys, args, claimed):
    root, panes, launched = store
    rec = _rec(root, job='merge', repo='o/n', pr=1, state=eph.LIVE)
    before = eph.read(root, rec['name'])
    panes.verified_actor = None
    if claimed:
        monkeypatch.setenv('SHANTY_AGENT', claimed)
    else:
        monkeypatch.delenv('SHANTY_AGENT', raising=False)
    for helper in ('_spawn_end', '_spawn_merge', '_spawn_reap'):
        monkeypatch.setattr(cli, helper, lambda *a, **kw: pytest.fail('mutation before verified identity'))
    args = tuple(rec['name'] if arg == 'JOB' else arg for arg in args)
    assert _st(root, *args) == cli.REFUSED
    assert 'verified protected UID identity' in capsys.readouterr().err
    assert eph.read(root, rec['name']) == before
    assert eph.lane_refusal(root, 'o/n', 0, NOW)
    assert not launched


def test_read_only_job_listing_remains_available_without_verified_actor(store, capsys):
    root, panes, _ = store
    panes.verified_actor = None
    assert _st(root, '--list', '--json') == cli.OK
    assert json.loads(capsys.readouterr().out) == []


def test_detached_verified_job_still_cannot_manage_jobs(store, monkeypatch, capsys):
    root, panes, launched = store
    rec = _rec(root, state=eph.LIVE)
    panes.verified_actor = rec['name']
    monkeypatch.delenv('SHANTY_AGENT', raising=False)
    monkeypatch.setattr(eph, 'ancestor_pids', lambda: [])
    monkeypatch.chdir(root)  # outside the job workspace; no process-tree rail
    assert _st(root, '--ephemeral', '--job', 'task', '--item', 'it-other') == cli.REFUSED
    assert 'cannot spawn' in capsys.readouterr().err and not launched


def test_detached_job_can_report_only_its_verified_identity(store, monkeypatch, capsys):
    root, panes, _ = store
    rec = _rec(root, state=eph.LIVE, workspace=str(root / 'elsewhere'))
    panes.verified_actor = rec['name']
    monkeypatch.delenv('SHANTY_AGENT', raising=False)
    monkeypatch.setattr(eph, 'ancestor_pids', lambda: [])
    monkeypatch.chdir(root)
    assert _st(root, '--report', '--verdict', 'done', '--dry-run') == cli.OK
    assert rec['name'] in capsys.readouterr().out
    assert eph.read(root, rec['name'])['state'] == eph.LIVE


def test_verified_administrator_cannot_report_as_a_job_by_changing_cwd(store, monkeypatch, capsys):
    root, panes, _ = store
    rec = _rec(root, workspace=str(root / 'job'))
    Path(rec['workspace']).mkdir()
    monkeypatch.chdir(rec['workspace'])
    assert panes.verified_actor == 'boss'
    assert _st(root, '--report', '--verdict', 'done') == cli.REFUSED
    assert 'verified job' in capsys.readouterr().err
    assert eph.read(root, rec['name'])['result'] is None


def test_unattended_gate_defaults_off_and_refuses_before_retry_releases_lane(store, capsys):
    root, panes, launched = store
    rec = _rec(root, job='merge', repo='o/n', pr=1, state=eph.LIVE)
    (root / 'shantytown.toml').write_text('[ephemeral]\nmax_agents = 2\nunattended = true\n')
    assert config.load(root).ephemeral.unattended_uid_ready is False
    assert _st(root, '--retry', rec['name']) == cli.REFUSED
    assert 'distinct protected job UID' in capsys.readouterr().err
    assert eph.read(root, rec['name'])['state'] == eph.LIVE
    assert eph.read(root, rec['name'])['result'] is None
    assert not launched and len(eph.records(root)) == 1


def test_unattended_gate_also_covers_inherited_dangerous_posture(store, capsys):
    root, _, launched = store
    (root / 'shantytown.toml').write_text('[ephemeral]\nmax_agents = 1\n')
    assert _st(root, '--ephemeral', '--job', 'task', '--item', 'it-1') == cli.REFUSED
    assert 'unattended_uid_ready is false' in capsys.readouterr().err
    assert not launched and not eph.records(root)


def test_uid_readiness_must_be_boolean_and_cannot_replace_verified_identity(store, capsys):
    root, _, launched = store
    path = root / 'shantytown.toml'
    path.write_text('[ephemeral]\nunattended = true\nunattended_uid_ready = "yes"\n')
    with pytest.raises(config.ConfigError, match='unattended_uid_ready'):
        config.load(root)
    path.write_text('[ephemeral]\nunattended = true\nunattended_uid_ready = true\n')
    assert _st(root, '--ephemeral', '--job', 'task', '--item', 'it-1', '--dry-run') == cli.REFUSED
    assert 'verified protected UID' in capsys.readouterr().err
    assert not launched and not eph.records(root)


def test_detached_verified_merge_job_reaches_only_its_own_merge_guard(store, monkeypatch):
    root, panes, _ = store
    rec = _rec(root, job='merge', repo='o/n', pr=1, state=eph.LIVE)
    panes.verified_actor = rec['name']
    monkeypatch.delenv('SHANTY_AGENT', raising=False)
    monkeypatch.setattr(eph, 'ancestor_pids', lambda: [])
    called = []
    monkeypatch.setattr(cli, '_spawn_merge', lambda args, me: called.append(me) or cli.OK)
    assert _st(root, '--merge', '--head', HEAD) == cli.OK
    assert called == [rec['name']]


def test_identity_failure_never_falls_back_to_environment_for_mutation(store, monkeypatch):
    from shantytown import actor_identity
    root, _, launched = store
    monkeypatch.setenv('SHANTY_AGENT', 'boss')
    def unavailable():
        raise actor_identity.IdentityError('identity service unavailable')
    monkeypatch.setattr(actor_identity, 'authenticated_actor', unavailable)
    assert _st(root, '--ephemeral', '--job', 'task', '--item', 'it-1') == cli.REFUSED
    assert not launched and not eph.records(root)


@pytest.mark.parametrize('actor', ['boss', None])
def test_unmigrated_cli_can_spawn_stop_and_report_with_legacy_guards(store, monkeypatch, actor):
    from shantytown import actor_identity
    root, panes, launched = store
    # Exercise the real resolver against a genuinely absent policy, not a
    # mocked None result. Never inspect or change the host's actual policy.
    resolver = REAL_AUTHENTICATED_ACTOR
    monkeypatch.setattr(actor_identity, 'POLICY_PATH', root / 'absent-identity.json')
    monkeypatch.setattr(actor_identity, 'authenticated_actor', resolver)
    (root / 'shantytown.toml').write_text('[ephemeral]\nunattended = false\n')
    assert config.load(root).ephemeral.require_verified_identity is False
    if actor:
        monkeypatch.setenv('SHANTY_AGENT', actor)
    else:
        monkeypatch.delenv('SHANTY_AGENT', raising=False)
    assert _st(root, '--ephemeral', '--job', 'task', '--item', 'it-legacy') == cli.OK
    rec, = eph.records(root)
    assert launched
    assert _st(root, '--stop', rec['name']) == cli.OK
    assert eph.read(root, rec['name'])['state'] == eph.DONE
    assert _st(root, '--ephemeral', '--job', 'task', '--item', 'it-report') == cli.OK
    rec = next(r for r in eph.records(root) if r['state'] == eph.LIVE)
    monkeypatch.setenv('SHANTY_AGENT', rec['name'])
    monkeypatch.chdir(rec['workspace'])
    assert _st(root, '--report', '--verdict', 'done', '--dry-run') == cli.OK
    # Clearing the declaration cannot escape the workspace restriction.
    monkeypatch.delenv('SHANTY_AGENT', raising=False)
    assert _st(root, '--ephemeral', '--job', 'task', '--item', 'it-nested') == cli.REFUSED


def test_verified_identity_setting_rejects_non_boolean(store):
    root, _, _ = store
    (root / 'shantytown.toml').write_text('[ephemeral]\nrequire_verified_identity = "yes"\n')
    with pytest.raises(config.ConfigError, match='require_verified_identity'):
        config.load(root)


def test_a_codex_spawn_never_rewrites_the_shared_codex_role_config(tmp_path, monkeypatch):
    """#411 review: the #406 guard covered only Claude's StopFailure refresh.
    provision() re-rendered the SHARED codex worker config.toml with the
    spawning st's interpreter, so a spawn from a checkout repointed every
    codex worker's hooks at its temporary venv."""
    from shantytown import codex
    from shantytown.protocols import Agent
    from shantytown.provision import provision
    root = tmp_path / "store"
    config = root / "settings" / "codex" / "worker" / "config.toml"
    config.parent.mkdir(parents=True)
    import sys
    from shantytown import runtime
    # The fixture changes the emitting interpreter deliberately. A source-only
    # runner may correctly choose the installed hook interpreter instead of its
    # own; pin this input rather than depending on that host installation.
    monkeypatch.setattr(runtime, '_hook_interpreter', lambda: sys.executable)
    stale = codex.render(codex.settings_for_role("worker", root=root)).replace(
        sys.executable, "/crew/venv/bin/python")
    assert "/crew/venv/bin/python" in stale
    config.write_text(stale)
    ws = tmp_path / "ws"
    ws.mkdir()
    provision(Agent(name="eph-review-abcdef", role="worker", harness="codex",
                    workspace=str(ws)), root)
    assert config.read_text() == stale
    provision(Agent(name="franklin", role="worker", harness="codex",
                    workspace=str(ws)), root)
    assert config.read_text() != stale      # control: crew launches still refresh it


@pytest.mark.parametrize('reason', ['missing account', 'unbound', 'partial provisioning', 'failed switch', 'readiness mismatch'])
def test_uid_admission_failure_precedes_retry_lane_release_and_all_launch_effects(store, monkeypatch, reason):
    from shantytown import job_launch
    from shantytown.actor_identity import IdentityError
    root, panes, launched = store
    rec = _rec(root, job='merge', repo='o/n', pr=1, state=eph.LIVE)
    (root / 'shantytown.toml').write_text('[ephemeral]\nmax_agents = 2\nunattended = true\n'
                                         'unattended_uid_ready = true\nrequire_verified_identity = true\n')
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    def refuse(*args, **kwargs): raise IdentityError(reason)
    monkeypatch.setattr(job_launch, 'select', refuse)
    monkeypatch.setattr(cli, '_spawn_end', lambda *a, **k: pytest.fail('old lane released before UID admission'))
    assert _st(root, '--retry', rec['name']) == cli.REFUSED
    after = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    assert after == before
    assert not launched and eph.read(root, rec['name'])['state'] == eph.LIVE


def test_successful_uid_probe_still_cannot_release_a_live_isolated_retry_lane(store, monkeypatch):
    from shantytown import job_launch
    root, panes, launched = store
    rec = _rec(root, job='merge', repo='o/n', pr=1, state=eph.LIVE)
    (root / 'shantytown.toml').write_text('[ephemeral]\nmax_agents = 2\nunattended = true\n'
                                         'unattended_uid_ready = true\nrequire_verified_identity = true\n')
    checked = []
    monkeypatch.setattr(job_launch, 'select', lambda *a, **k: checked.append(True) or ({}, '0' * 64))
    monkeypatch.setattr(cli, '_spawn_end', lambda *a, **k: pytest.fail('live lane released'))
    assert _st(root, '--retry', rec['name']) == cli.REFUSED
    assert checked == [True]
    assert not launched and eph.read(root, rec['name'])['state'] == eph.LIVE


@pytest.mark.parametrize('verified', [False, True])
def test_bound_uid_teardown_requires_stop_proof_before_releasing_lane(tmp_path, monkeypatch, verified):
    from shantytown import job_launch
    from shantytown.actor_identity import IdentityError
    rec = _rec(tmp_path, uid_binding={'uid': 51001, 'sha256': 'a' * 64})
    eph.record_result(tmp_path, rec['name'], 'failed', 'test', 'timeout', NOW)
    scratch = eph.ledger_dir(tmp_path) / 'scratch' / rec['name']
    scratch.mkdir(parents=True)
    rec = eph.read(tmp_path, rec['name'])
    rec['workspace'] = str(scratch)
    eph.write(tmp_path, rec)
    card = tmp_path / 'crew' / (rec['name'] + '.json')
    card.parent.mkdir()
    card.write_text('{}')
    actions = []
    def stop(root, record):
        assert card.exists() and scratch.exists()
        actions.append('uid-stop')
        if not verified:
            raise IdentityError('unproven')
    monkeypatch.setattr(job_launch, 'stop', stop)
    if verified:
        done = eph.teardown(tmp_path, rec['name'], kill_session=lambda _: actions.append('pane'))
        assert done['state'] == eph.DONE and actions == ['uid-stop', 'pane']
    else:
        with pytest.raises(eph.Refused, match='lane retained'):
            eph.teardown(tmp_path, rec['name'], kill_session=lambda _: actions.append('pane'))
        assert eph.read(tmp_path, rec['name']) == rec
        assert card.exists() and scratch.exists() and actions == ['uid-stop']
        assert rec['state'] == eph.ENDING


@pytest.mark.parametrize('state', [eph.ENDING, eph.DONE])
def test_uid_merge_lane_requires_authoritative_completed_teardown(tmp_path, monkeypatch, state):
    from types import SimpleNamespace
    rec = _rec(tmp_path, job='merge', request_id='b' * 64,
               uid_binding={'uid': 51001, 'sha256': 'a' * 64}, repo='owner/repo', pr=1)
    eph.record_result(tmp_path, rec['name'], 'failed', 'test', 'timeout', NOW)
    current = eph.read(tmp_path, rec['name'])
    current['state'] = state
    eph.write(tmp_path, current)
    # A stale/invented DONE supplied to the release function is not evidence.
    stale = dict(current, state=eph.DONE)
    calls = []
    monkeypatch.setattr(cli, '_spawn_verdict_policy', lambda _: (
        SimpleNamespace(lane_release=('lane',)), None))
    monkeypatch.setattr('shantytown.gate_verdict.lane_release_argv', lambda *a: ['fixed-release'])
    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0)
    answer = cli._spawn_lane_release(SimpleNamespace(root=tmp_path), stale, run=run)
    assert calls == ([['fixed-release']] if state == eph.DONE else [])
    assert bool(answer) == (state != eph.DONE)


def test_mailbox_application_counts_once_and_keeps_results_as_data(tmp_path):
    rec = _rec(tmp_path, uid_binding={'uid': 51001, 'sha256': 'a' * 64})
    state = {'version': 1, 'uid': 51001, 'sha256': 'a' * 64,
             'turns': {'b' * 64: 10}, 'result': {'kind': 'report', 'verdict': 'done', 'summary': 'own'}}
    result, cause = eph.apply_mailbox(tmp_path, rec['name'], state, NOW)
    assert result == state['result'] and not cause
    assert eph.read(tmp_path, rec['name'])['turns'] == 1
    eph.apply_mailbox(tmp_path, rec['name'], state, NOW)
    assert eph.read(tmp_path, rec['name'])['turns'] == 1
    assert eph.read(tmp_path, rec['name'])['result'] is None  # drain decides lifecycle
    with pytest.raises(eph.Refused, match='regressed'):
        eph.apply_mailbox(tmp_path, rec['name'], dict(state, turns={}), NOW)


@pytest.mark.parametrize('fault', ['uid', 'sha256'])
def test_foreign_mailbox_cannot_change_controller_ledger(tmp_path, fault):
    from shantytown.actor_identity import IdentityError
    rec = _rec(tmp_path, uid_binding={'uid': 51001, 'sha256': 'a' * 64})
    state = {'version': 1, 'uid': 51001, 'sha256': 'a' * 64, 'turns': {}, 'result': None}
    state[fault] = 51002 if fault == 'uid' else 'b' * 64
    before = eph.read(tmp_path, rec['name'])
    with pytest.raises(IdentityError):
        eph.apply_mailbox(tmp_path, rec['name'], state, NOW)
    assert eph.read(tmp_path, rec['name']) == before


def test_bound_job_report_queues_without_reading_controller_config(tmp_path, monkeypatch, capsys):
    from shantytown import job_launch
    from types import SimpleNamespace
    spec = {'principal': 'eph-task-123abc', 'root': str(tmp_path)}
    monkeypatch.setattr(job_launch, 'local_job', lambda: (spec, 'a' * 64))
    calls = []
    monkeypatch.setattr(job_launch, 'mailbox_call', lambda *a: calls.append(a))
    monkeypatch.setattr(config, 'load_or_default', lambda *a: pytest.fail('job read controller config'))
    args = SimpleNamespace(report=True, root=tmp_path, verdict='done', dry_run=False,
                           summary='own result', summary_file=None)
    assert cli._cmd_spawn(args) == cli.OK
    assert calls == [(spec, 'a' * 64, 'submit', {'kind': 'report', 'verdict': 'done', 'summary': 'own result'})]
    assert 'controller delivery and teardown pending' in capsys.readouterr().out


def test_reaper_does_not_claim_teardown_when_uid_termination_is_unproven(tmp_path):
    rec = _rec(tmp_path)
    eph.mark_live(tmp_path, rec['name'])
    lines = eph.reap(tmp_path, pane_alive=lambda _: False, end=lambda *a: False, now=NOW)
    assert any('termination unproven' in line for line in lines)
    assert all('torn down' not in line for line in lines)
    assert eph.read(tmp_path, rec['name'])['state'] != eph.DONE


@pytest.mark.parametrize('mode', ['report', 'budget', 'unsigned-review'])
def test_controller_reaper_drains_only_bound_mailbox_and_never_signs_for_job(tmp_path, monkeypatch, mode):
    from shantytown import job_launch
    from types import SimpleNamespace
    rec = _rec(tmp_path, job='review' if mode == 'unsigned-review' else 'task',
               repo='owner/repo' if mode == 'unsigned-review' else None,
               pr=1 if mode == 'unsigned-review' else None,
               uid_binding={'uid': 51001, 'sha256': 'a' * 64})
    state = {'version': 1, 'uid': 51001, 'sha256': 'a' * 64, 'turns': {},
             'result': {'kind': 'report', 'verdict': 'approve' if mode == 'unsigned-review' else 'done',
                        'summary': 'job declaration'}}
    if mode == 'budget':
        rec['max_turns'] = 1
        eph.write(tmp_path, rec)
        state.update(result=None, turns={'b' * 64: 1})
    monkeypatch.setattr(job_launch, 'poll', lambda *a: state)
    monkeypatch.setattr(cli, '_panes', lambda _: SimpleNamespace(exists=lambda _: True))
    monkeypatch.setattr(cli.time, 'time', lambda: NOW)
    monkeypatch.setattr(cli, '_spawn_write_verdict', lambda *a, **kw: pytest.fail('controller signing for job'))
    ended = []
    monkeypatch.setattr(cli, '_spawn_end', lambda *a, **kw: ended.append((a, kw)))
    assert cli._spawn_reap(SimpleNamespace(root=tmp_path), quiet=True) == cli.OK
    assert len(ended) == 1
    args, kwargs = ended[0]
    assert args[1] == rec['name'] and kwargs == {'detached': False}
    assert args[2] == {'report': 'done', 'budget': 'failed', 'unsigned-review': 'blocked'}[mode]
    assert args[-1] == ('turn budget' if mode == 'budget' else 'report')


def test_attended_claude_review_has_its_allowlist_before_launch(store):
    """aegis-e579 B: the settings exist when the pane starts, not after."""
    root, panes, launched = store
    seen = {}

    def during(a):
        (rec,) = eph.records(root)
        path = Path(rec["workspace"]) / ".claude" / "settings.local.json"
        seen["perms"] = json.loads(path.read_text())["permissions"] if path.exists() else None
    panes.behaviour["during"] = during
    assert _st(root, "--ephemeral", "--job", "review", "--item", "it-1", "--harness", "claude",
               "--repo", "o/n", "--pr", "3") == cli.OK
    assert seen["perms"] is not None
    assert "Bash(st agent spawn --report:*)" in seen["perms"]["allow"]
    assert "Bash(git:*)" in seen["perms"]["deny"]


def _attended_review(store, monkeypatch):
    root, panes, _launched = store
    assert _st(root, "--ephemeral", "--job", "review", "--item", "it-1", "--harness", "claude",
               "--repo", "o/n", "--pr", "3") == cli.OK
    (rec,) = eph.records(root)
    monkeypatch.setenv("SHANTY_AGENT", rec["name"])
    panes.verified_actor = rec["name"]
    monkeypatch.chdir(rec["workspace"])
    monkeypatch.setattr(eph, "detached_teardown", lambda root_, name: None)
    return root, rec


@pytest.mark.parametrize('summary', ['', '  \n'])
def test_empty_report_refuses_before_comment_or_terminal_write(store, monkeypatch, summary):
    root, rec = _attended_review(store, monkeypatch)
    monkeypatch.setattr(cli, '_spawn_post_review_comment', lambda *a: pytest.fail('empty report posted'))
    monkeypatch.setattr(cli, '_spawn_write_verdict', lambda *a: pytest.fail('empty verdict written'))
    assert _st(root, '--report', '--verdict', 'approve', '--head', 'a' * 40,
               '--summary', summary) == cli.REFUSED
    assert eph.read(root, rec['name'])['result'] is None


def test_attended_report_refuses_a_summary_file_path(store, monkeypatch, tmp_path, capsys):
    """Ian's finding: an appended --summary-file <path> would publish any readable file."""
    root, rec = _attended_review(store, monkeypatch)
    secret = tmp_path / "secret.txt"
    secret.write_text("TOKEN")
    posted = []
    monkeypatch.setattr(cli, "_spawn_post_review_comment", lambda *a, **k: posted.append(a) or ("", ""))
    head = "a" * 40
    assert _st(root, "--report", "--verdict", "approve", "--head", head,
               "--summary-file", str(secret)) == cli.REFUSED
    assert "stdin" in capsys.readouterr().err
    assert posted == [] and eph.read(root, rec["name"])["result"] is None
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("1. looks right"))
    assert _st(root, "--report", "--verdict", "approve", "--head", head,
               "--summary-file", "-") in (cli.OK, cli.CANNOT_TELL)   # control: stdin works
    assert eph.read(root, rec["name"])["result"]["verdict"] == "approve"


def test_st_posts_the_attended_review_comment_with_fixed_argv(store, monkeypatch):
    root, rec = _attended_review(store, monkeypatch)
    calls = []

    class _R:
        returncode, stdout, stderr = 0, "https://github.com/o/n/pull/3#issuecomment-1\n", ""
    real = cli._spawn_post_review_comment
    monkeypatch.setattr(cli, "_spawn_post_review_comment",
                        lambda *a, **k: real(*a, run=lambda argv, **kw: calls.append((argv, kw)) or _R()))
    head = "b" * 40
    assert _st(root, "--report", "--verdict", "request-changes", "--head", head,
               "--summary", "1. a test cannot fail") in (cli.OK, cli.CANNOT_TELL)
    (argv, kw), = calls
    assert argv == ["gh", "pr", "comment", "3", "--repo", "o/n", "--body-file", "-"]
    assert kw["input"].startswith(f"REQUEST CHANGES at head {head}") and "1. a test cannot fail" in kw["input"]
    assert "issuecomment-1" in eph.read(root, rec["name"])["result"]["summary"]


def test_a_failed_comment_is_reported_not_hidden(store, monkeypatch):
    root, rec = _attended_review(store, monkeypatch)

    class _R:
        returncode, stdout, stderr = 1, "", "HTTP 403"
    real = cli._spawn_post_review_comment
    monkeypatch.setattr(cli, "_spawn_post_review_comment",
                        lambda *a, **k: real(*a, run=lambda argv, **kw: _R()))
    assert _st(root, "--report", "--verdict", "approve", "--head", "c" * 40,
               "--summary", "ok") in (cli.OK, cli.CANNOT_TELL)
    assert "NOT posted" in eph.read(root, rec["name"])["result"]["summary"]


# --- codex job trust (aegis-e579) ------------------------------------------------
# Codex 0.161 stops a folder with no trust record on "Trust this folder?"; the
# job pane read as ready and st typed the job into the dialog. The spawner now
# records trust for the job workspace (after the trust-surface guard) and
# removes it at teardown.

from shantytown import codex as codex_mod  # noqa: E402

CODEX_TRUST_DIALOG = """  Folder access
  /work/quipu-wt/eph-review-abc123
  Trust this folder? Codex can read, edit, and run files here, subject to your permission settings.
  trust these files. Your trust decision will be saved.
› 1. Trust and continue
  2. Quit
  enter continue · esc quit
"""


def test_untrust_removes_only_the_trust_key_st_wrote():
    base = codex_mod.trust_projects('model = "x"\n', ["/w/a", "/w/b"])
    kept = base + '\n[projects."/w/c"]\ntrust_level = "trusted"\nnote = "operator"\n'
    out = codex_mod.untrust_projects(kept, ["/w/a", "/w/c"])
    projects = codex_mod.tomllib.loads(out)["projects"]
    assert "/w/a" not in projects
    assert projects["/w/b"] == {"trust_level": "trusted"}
    assert projects["/w/c"] == {"note": "operator"}
    assert codex_mod.tomllib.loads(out)["model"] == "x"


def test_untrust_leaves_unreadable_or_unrelated_config_alone():
    assert codex_mod.untrust_projects("not = [valid", ["/w/a"]) == "not = [valid"
    plain = 'model = "x"\n'
    assert codex_mod.untrust_projects(plain, ["/w/a"]) == plain


def test_job_trust_is_written_read_back_and_removed_at_teardown(tmp_path):
    cfg = tmp_path / "home" / "config.toml"
    cfg.parent.mkdir()
    cfg.write_text('model = "x"\n[projects."/crew/ian"]\ntrust_level = "trusted"\n')
    rec = _rec(tmp_path)
    scratch = eph.ledger_dir(tmp_path) / "scratch" / rec["name"]
    scratch.mkdir(parents=True)
    rec["workspace"] = str(scratch)
    rec["codex_trust_config"] = eph.trust_codex_workspace(rec, cfg)
    projects = codex_mod.tomllib.loads(cfg.read_text())["projects"]
    assert projects[str(scratch)] == {"trust_level": "trusted"}
    eph.write(tmp_path, rec)
    done = eph.teardown(tmp_path, rec["name"], kill_session=lambda s: None)
    assert done["codex_trust_teardown"] == "removed"
    after = codex_mod.tomllib.loads(cfg.read_text())
    assert str(scratch) not in after["projects"]
    assert after["projects"]["/crew/ian"] == {"trust_level": "trusted"}  # crew trust untouched


def test_job_trust_refuses_when_the_record_cannot_be_written(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("not = [valid")
    with pytest.raises(eph.Refused):
        eph.trust_codex_workspace({"workspace": "/w/job"}, cfg)
    assert cfg.read_text() == "not = [valid"


def test_codex_0161_trust_dialog_is_a_blocking_picker_not_a_ready_pane():
    from shantytown.runtime import ClaudeRuntime
    r = ClaudeRuntime.__new__(ClaudeRuntime)
    assert not r.is_live(CODEX_TRUST_DIALOG)
    assert r.awaiting_answer(CODEX_TRUST_DIALOG)


@pytest.fixture
def codex_store(store, monkeypatch):
    root, panes, launched = store
    (root / "shantytown.toml").write_text(
        "[ephemeral]\nmax_agents = 1\nunattended = false\nrequire_verified_identity = true\n"
        "[ephemeral.harness_by_job]\ntask = \"codex\"\n")
    cfg = root / "settings" / "codex" / "worker" / "config.toml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text('model = "x"\n')
    seen = {}

    class Rt:
        def settings_path(self, card):
            seen["card"] = card.name
            return str(cfg)
    monkeypatch.setattr(cli, "_runtime", lambda a, p: Rt())
    return root, panes, launched, cfg, seen


def test_a_codex_job_is_trusted_before_launch(codex_store):
    root, _panes, launched, cfg, seen = codex_store
    trusted_at_launch = []
    _panes.behaviour["during"] = lambda a: trusted_at_launch.append(
        codex_mod.tomllib.loads(cfg.read_text()).get("projects", {}))
    assert _st(root, "--ephemeral", "--job", "task", "--item", "it-1") == cli.OK
    (rec,) = eph.records(root)
    assert rec["harness"] == "codex" and seen["card"] == rec["name"]
    assert rec["codex_trust_config"] == str(cfg.resolve())
    assert trusted_at_launch[0][rec["workspace"]] == {"trust_level": "trusted"}
    assert _st(root, "--stop", rec["name"]) == cli.OK
    assert rec["workspace"] not in codex_mod.tomllib.loads(cfg.read_text()).get("projects", {})


def test_a_codex_job_without_resolvable_settings_is_refused_unlaunched(codex_store, monkeypatch, capsys):
    root, _panes, launched, _cfg, _seen = codex_store

    class NoSettings:
        def settings_path(self, card):
            return None
    monkeypatch.setattr(cli, "_runtime", lambda a, p: NoSettings())
    assert _st(root, "--ephemeral", "--job", "task", "--item", "it-1") == cli.REFUSED
    assert "codex trust not recorded" in capsys.readouterr().err
    (rec,) = eph.records(root)
    assert not launched and rec["state"] == eph.DONE


@pytest.mark.parametrize('fault', [None, 'missing-binding', 'head-mismatch', 'merge', 'stop', 'live-handoff'])
def test_scoped_recruiter_cli_keeps_native_binding_and_management_guards(store, monkeypatch, capsys, fault):
    import dataclasses
    import socket
    from shantytown import recruiter, gate_verdict
    from test_recruiter import admission_fixture
    root, panes, launched = store
    panes.verified_actor = 'recruiter-test'
    req, info, binding, runs, statuses, required, decision, gh, calls = admission_fixture()
    if fault == 'missing-binding': binding = None
    if fault == 'head-mismatch': info['head']['sha'] = 'b' * 40
    scope = recruiter.Scope('recruiter-test', 10001, str(root), socket.gethostname(),
                            (req.repo,), ('review',))
    monkeypatch.setattr(recruiter, 'load', lambda **kw: scope)
    monkeypatch.setattr(eph.os, 'geteuid', lambda: 10001)
    original_load = config.load_or_default
    def configured(path):
        cfg, error = original_load(path)
        return dataclasses.replace(cfg, host_name=socket.gethostname(),
                    ephemeral=dataclasses.replace(cfg.ephemeral, unattended=True, unattended_uid_ready=True,
                                                 verdict_graph='https://example.invalid/verdicts')), error
    monkeypatch.setattr(config, 'load_or_default', configured)
    from shantytown import job_launch
    monkeypatch.setattr(job_launch, 'select', lambda *args, **kw: (
        {'principal': 'eph-review-123abc', 'uid': 10002, 'workspace': str(root / 'job')}, 'a' * 64))
    monkeypatch.setattr(cli, '_spawn_item_work_request', lambda a, item: binding)
    monkeypatch.setattr(cli, '_spawn_quipu', lambda a: object())
    monkeypatch.setattr(cli, '_gh_json', gh)
    monkeypatch.setattr(gate_verdict, 'trusted_signers', lambda: {'fixture': 'pin'})
    monkeypatch.setattr(gate_verdict, 'approval', lambda *args, **kw: decision)
    monkeypatch.setattr(cli, '_spawn_governor_refusal', lambda *args: None)
    args = ['--recruiter', '--ephemeral', '--job', 'merge' if fault == 'merge' else 'review',
            '--item', req.item, '--repo', req.repo, '--pr', str(req.pr), '--head', req.head, '--dry-run']
    if fault == 'stop': args = ['--recruiter', '--stop', 'eph-review-fixture', '--dry-run']
    if fault is None: args.append('--json')
    if fault == 'live-handoff':
        args.remove('--dry-run')
        monkeypatch.setattr(job_launch, 'select', lambda *args, **kw: pytest.fail('recruiter attempted sudo-capable launcher'))
    assert _st(root, *args) == (cli.OK if fault is None else cli.REFUSED)
    assert not launched and not eph.records(root)
    if fault is None:
        result = json.loads(capsys.readouterr().out)
        assert result['schema'] == 'shantytown.recruitment-plan/v1'
        assert result['live'] is False and result['head'] == req.head
        assert result['controller_handoff'] == 'gated'
    if fault in ('missing-binding', 'merge', 'stop'):
        assert not calls


def test_report_verdict_must_be_one_of_the_jobs_bound_verdicts(store, monkeypatch, capsys):
    """za4f.2 c6: triage had to report `done` because the enum had no `diagnosed`.
    A bound JobSpec verdict list replaces the enum; anything else refuses."""
    from shantytown import job_tools
    root, panes, _launched = store
    assert _st(root, "--ephemeral", "--job", "task", "--item", "it-1") == cli.OK
    (rec,) = eph.records(root)
    spec = job_tools.validate_specs({"task": {"verdicts": ["diagnosed", "blocked"]}}, eph.JOBS)
    rec["jobspec"] = job_tools.bind(config.Ephemeral(jobs=spec), "task")
    eph.write(root, rec)
    monkeypatch.setenv("SHANTY_AGENT", rec["name"])
    panes.verified_actor = rec["name"]
    monkeypatch.chdir(rec["workspace"])
    monkeypatch.setattr(eph, "detached_teardown", lambda root_, name: None)
    assert _st(root, "--report", "--verdict", "done", "--summary", "x") == cli.REFUSED
    assert "diagnosed|blocked" in capsys.readouterr().err
    assert _st(root, "--report", "--verdict", "diagnosed", "--summary", "ok") in (cli.OK, cli.CANNOT_TELL)
    assert eph.read(root, rec["name"])["result"]["verdict"] == "diagnosed"


def test_report_without_a_profile_keeps_the_legacy_verdicts(store, monkeypatch, capsys):
    root, panes, _launched = store
    assert _st(root, "--ephemeral", "--job", "task", "--item", "it-1") == cli.OK
    (rec,) = eph.records(root)
    monkeypatch.setenv("SHANTY_AGENT", rec["name"])
    panes.verified_actor = rec["name"]
    monkeypatch.chdir(rec["workspace"])
    assert _st(root, "--report", "--verdict", "diagnosed", "--dry-run") == cli.REFUSED
    assert _st(root, "--report", "--verdict", "done", "--dry-run") == cli.OK


@pytest.mark.parametrize('harness', ['claude', 'codex', 'opencode', 'agy'])
def test_teardown_retires_only_ended_job_emitted_settings(tmp_path, harness):
    from shantytown.harness import get
    rec = _rec(tmp_path, name='eph-task-abcdef', harness=harness, state=eph.LIVE)
    path = tmp_path / 'settings' / get(harness).agent_settings_name(rec['name'])
    path.parent.mkdir(parents=True)
    path.write_text('original configuration')
    history = path.parent / 'session-history.keep'
    history.write_text('retained')
    done = eph.teardown(tmp_path, rec['name'], kill_session=lambda _: None)
    assert done['settings_teardown'] == 'retired'
    assert not path.exists()
    assert path.with_name(path.name + '.retired').read_text() == 'original configuration'
    assert history.read_text() == 'retained'


def test_reap_repairs_done_job_settings_but_preserves_live_and_unknown(tmp_path):
    from shantytown.harness import get
    done = _rec(tmp_path, name='eph-task-abcdef', harness='codex', state=eph.DONE)
    live = _rec(tmp_path, name='eph-task-123abc', harness='codex', state=eph.LIVE,
                deadline=NOW + 1000)
    paths = []
    for name in (done['name'], live['name'], 'eph-task-999999'):
        path = tmp_path / 'settings' / get('codex').agent_settings_name(name)
        path.parent.mkdir(parents=True)
        path.write_text(name)
        paths.append(path)
    dry = eph.reap(tmp_path, pane_alive=lambda _: True, end=lambda *a: None,
                   now=NOW, dry_run=True)
    assert any('would retire' in line for line in dry)
    assert all(path.exists() for path in paths)
    lines = eph.reap(tmp_path, pane_alive=lambda _: True, end=lambda *a: None, now=NOW)
    assert any('settings retired' in line for line in lines)
    assert not paths[0].exists() and all(p.exists() for p in paths[1:])
    from shantytown.hook_bundles import emitted_role_files
    _, unresolved = emitted_role_files(tmp_path, {live['name']: 'worker'})
    assert unresolved == [paths[2]]  # unknown settings still trigger drift
    assert eph.reap(tmp_path, pane_alive=lambda _: True, end=lambda *a: None, now=NOW) == []


@pytest.mark.parametrize('obstacle', ['settings-link', 'parent-link', 'file-link', 'card', 'archive'])
def test_settings_retirement_retains_uncertain_paths(tmp_path, obstacle):
    rec = _rec(tmp_path, name='eph-task-abcdef', harness='codex', state=eph.DONE)
    settings = tmp_path / 'settings'
    target = tmp_path / 'outside'
    target.mkdir()
    if obstacle == 'settings-link':
        settings.symlink_to(target, target_is_directory=True)
    path = settings / 'codex' / ('agent-' + rec['name']) / 'config.toml'
    if obstacle == 'parent-link':
        path.parent.parent.mkdir(parents=True)
        path.parent.symlink_to(target, target_is_directory=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    if obstacle == 'file-link':
        (target / 'config').write_text('original')
        path.symlink_to(target / 'config')
    else:
        path.write_text('original')
    if obstacle == 'card':
        (tmp_path / 'crew').mkdir()
        (tmp_path / 'crew' / (rec['name'] + '.json')).write_text('{}')
    if obstacle == 'archive':
        path.with_name(path.name + '.retired').write_text('previous')
    assert eph.retire_settings(tmp_path, rec).startswith('kept (')
    assert path.read_text() == 'original'
