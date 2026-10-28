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
    req = eph.Request(job=kw.pop("job", "task"), item=kw.pop("item", "it-1"),
                      repo=kw.pop("repo", None), pr=kw.pop("pr", None))
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
    first.update(state=eph.DONE, ended_at=NOW)
    eph.write(tmp_path, first)
    with pytest.raises(eph.Refused, match="10m apart"):
        _rec(tmp_path, job="merge", repo="o/n", pr=2, now=NOW + 60)
    _rec(tmp_path, job="merge", repo="o/n", pr=2, now=NOW + 601)


# --- the prompt ---------------------------------------------------------------

def test_review_prompt_is_independent_and_never_merges(tmp_path):
    text = eph.prompt(_rec(tmp_path, job="review", repo="o/n", pr=7))
    assert "NON-AUTHOR" in text and "gh pr review 7 --repo o/n --approve" in text
    assert "NEVER push, never merge" in text
    assert "st agent spawn --report --verdict" in text


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


def test_uid_readiness_must_be_boolean_and_only_enables_a_preview(store, capsys):
    root, _, launched = store
    path = root / 'shantytown.toml'
    path.write_text('[ephemeral]\nunattended = true\nunattended_uid_ready = "yes"\n')
    with pytest.raises(config.ConfigError, match='unattended_uid_ready'):
        config.load(root)
    path.write_text('[ephemeral]\nunattended = true\nunattended_uid_ready = true\n')
    assert _st(root, '--ephemeral', '--job', 'task', '--item', 'it-1', '--dry-run') == cli.OK
    assert 'would spawn' in capsys.readouterr().out
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
