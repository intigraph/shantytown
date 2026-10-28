"""st agent spawn --ephemeral (aegis-c01c.2): supervised, administrator-managed
agents for one job. Every supervision rule gets a test that shows it saying NO,
because a check that cannot fail proves nothing (AGENTS.md)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

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
    rec = eph.plan(req, root=root, policy=kw.pop("policy", _policy(max_agents=10)), actor=None,
                   administrator="boss", host=None, now=kw.pop("now", NOW),
                   role_of=lambda n: None, name=kw.pop("name", None))
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


def test_only_the_administrator_or_a_human_manages_them():
    roles = {"boss": "administrator", "lex": "worker", "lead1": "lead"}.get
    eph.authority(None, roles)
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
                 actor=None, administrator=None, host=None, now=NOW,
                 role_of=lambda n: None)


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
    (root / "shantytown.toml").write_text("[ephemeral]\nmax_agents = 1\n")
    panes = NullPanes(live=set())
    monkeypatch.setattr(cli, "_panes", lambda a: panes)
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
    assert card["dangerous"] is True and card["harness"] == "claude"
    assert launched[0].name == rec["name"]
    assert Path(rec["workspace"]).is_dir()
    assert _st(root, "--ephemeral", "--job", "task", "--item", "it-2") == cli.REFUSED
    assert "over cap" in capsys.readouterr().err
    assert len(launched) == 1


def test_a_worker_cannot_spawn(store, monkeypatch, capsys):
    root, _panes, launched = store
    (root / "crew" / "lex.json").write_text(json.dumps({"role": "worker"}))
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
    assert "own pane" in capsys.readouterr().err


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


def test_report_needs_the_process_to_be_the_job_not_just_the_env(store, monkeypatch, capsys):
    """Live review finding: a crew pane exporting SHANTY_AGENT=<job> could forge
    that job's verdict. The process must be inside the job."""
    root, panes, _launched = store
    assert _st(root, "--ephemeral", "--job", "task", "--item", "it-1") == cli.OK
    (rec,) = eph.records(root)
    monkeypatch.setenv("SHANTY_AGENT", rec["name"])
    assert _st(root, "--report", "--verdict", "done") == cli.REFUSED   # not inside it
    assert "own pane" in capsys.readouterr().err
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
