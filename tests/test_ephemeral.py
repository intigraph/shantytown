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
                      request_id=kw.pop("request_id", None),
                      harness=kw.pop("harness", None), track=kw.pop("track", None))
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


def test_config_reads_and_refuses_the_job_model_table(tmp_path):
    """aegis-jsp0: [ephemeral.model_by_harness] names the model a job runs."""
    (tmp_path / "shantytown.toml").write_text(
        "[ephemeral.model_by_harness]\nclaude = \"claude-opus-5-5\"\n")
    assert config.load(tmp_path).ephemeral.model_by_harness == {"claude": "claude-opus-5-5"}
    assert config.load_or_default(tmp_path / "absent")[0].ephemeral.model_by_harness == {}
    for bad in ('claude = ""', "claude = 5", "claude = \"  \""):
        (tmp_path / "shantytown.toml").write_text(f"[ephemeral.model_by_harness]\n{bad}\n")
        with pytest.raises(config.ConfigError, match="model_by_harness.claude"):
            config.load(tmp_path)


def test_job_model_is_per_harness_and_absent_means_none():
    p = _policy(model_by_harness={"claude": "claude-opus-5-5"})
    assert eph.model_for("claude", p) == "claude-opus-5-5"
    # A claude slug never reaches a codex job, and no table means no model.
    assert eph.model_for("codex", p) is None
    assert eph.model_for("claude", _policy()) is None


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


def test_over_cap_is_overcap_spawning_off_is_refused_and_done_jobs_free_the_slot(tmp_path):
    _rec(tmp_path, name="eph-task-000001")
    with pytest.raises(eph.OverCap, match="over cap: 1/1"):
        _rec(tmp_path, policy=_policy(max_agents=1))
    # Spawning switched off is a refusal, never a queue: nothing would drain it.
    with pytest.raises(eph.Refused, match="off") as off:
        _rec(tmp_path, policy=_policy(max_agents=0))
    assert not isinstance(off.value, eph.OverCap)
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
    assert "OTHER than the author" in text and 'review policy for o/n is "none"' in text


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
    # No test reaches the real forge. A test that needs an answer stubs its own.
    def offline_gh(*args):
        raise RuntimeError("offline fixture")
    monkeypatch.setattr(cli, "_gh_json", offline_gh)
    # A task job must name --repo (aegis-za4f.15), and a named repo must resolve
    # a real checkout to cut from, so `--repo o/n` lands on this one-commit
    # clone unless a test stubs its own.
    import subprocess
    src = tmp_path / "fixture-src"
    subprocess.run(["git", "init", "-q", "-b", "main", str(src)], check=True)
    subprocess.run(["git", "-C", str(src), "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    monkeypatch.setattr(cli, "_resolve_repo", lambda name: src)
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


def test_spawn_launches_a_supervised_card_then_queues_over_cap(store, capsys):
    root, panes, launched = store
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-1") == cli.OK
    (rec,) = eph.records(root)
    card = json.loads((root / "crew" / f"{rec['name']}.json").read_text())
    assert card["reports_to"] == "boss" and card["roles"] == ["worker", "first"]
    assert card["dangerous"] is False and card["harness"] == "claude"
    assert launched[0].name == rec["name"]
    assert Path(rec["workspace"]).is_dir()
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-2") == cli.OK
    assert "QUEUED q-" in capsys.readouterr().out
    assert len(launched) == 1 and len(eph.records(root)) == 1


def _launch_line(root, card):
    """The real Claude launch line for the card spawn handed to _launch."""
    from shantytown.harness import ClaudeHarness
    return ClaudeHarness().launch(card, str(root / "settings.json"), root=root)


def test_spawn_puts_the_configured_model_on_the_job_card_and_its_launch(store):
    """aegis-jsp0: one configured value is BOTH --model and SHANTY_MODEL, so the
    model a job declares to Quipu (X-Quipu-Model) is the one it runs."""
    root, _panes, launched = store
    toml = root / "shantytown.toml"
    toml.write_text(toml.read_text()
                    + "[ephemeral.model_by_harness]\nclaude = \"claude-opus-5-5\"\n")
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-1") == cli.OK
    (rec,) = eph.records(root)
    assert rec["model"] == "claude-opus-5-5"
    card_json = json.loads((root / "crew" / f"{rec['name']}.json").read_text())
    assert card_json["model"] == "claude-opus-5-5"
    assert launched[0].model == "claude-opus-5-5"
    line = _launch_line(root, launched[0])
    assert "--model claude-opus-5-5" in line and "SHANTY_MODEL=claude-opus-5-5 " in line


def test_spawn_without_a_configured_job_model_declares_none(store):
    """No entry -> no model on the card, no --model, no SHANTY_MODEL: the harness
    default is never reported as if declared."""
    root, _panes, launched = store
    toml = root / "shantytown.toml"
    toml.write_text(toml.read_text()
                    + "[ephemeral.model_by_harness]\ncodex = \"gpt-5.5\"\n")
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-1") == cli.OK
    (rec,) = eph.records(root)
    assert rec["model"] is None and launched[0].model is None
    assert "model" not in json.loads((root / "crew" / f"{rec['name']}.json").read_text())
    line = _launch_line(root, launched[0])
    assert "--model" not in line and "SHANTY_MODEL=" not in line.replace("-u SHANTY_MODEL", "")


def test_a_worker_cannot_spawn(store, monkeypatch, capsys):
    root, _panes, launched = store
    (root / "crew" / "lex.json").write_text(json.dumps({"role": "worker"}))
    _panes.verified_actor = "lex"
    monkeypatch.setenv("SHANTY_AGENT", "lex")
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-1") == cli.REFUSED
    assert "not the administrator" in capsys.readouterr().err and not launched


def test_a_lead_can_spawn_and_stop(store, monkeypatch, capsys):
    """aegis-za4f: leads manage ephemeral jobs too; cap and identity still apply."""
    root, panes, launched = store
    (root / "crew" / "lea.json").write_text(json.dumps({"role": "lead", "reports_to": "boss"}))
    panes.verified_actor = "lea"
    monkeypatch.setenv("SHANTY_AGENT", "lea")
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-1") == cli.OK
    (rec,) = eph.records(root)
    assert len(launched) == 1
    # The cap is unchanged for a lead: max_agents = 1 in the fixture.
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-2") == cli.OK
    assert "QUEUED" in capsys.readouterr().out and len(launched) == 1
    (t,) = eph.tickets(root)
    assert t["requester"] == "lea"
    assert _st(root, "--stop", rec["name"]) == cli.OK
    assert eph.read(root, rec["name"])["state"] == eph.DONE


def test_lead_admission_is_opt_in_so_the_controller_boundary_stays_administrator():
    """authority() defaults to administrator-only; only the job paths admit leads."""
    roles = {"lea": "lead", "lex": "worker", "boss": "administrator"}.get
    with pytest.raises(eph.Refused, match="not the administrator; ephemeral"):
        eph.authority("lea", roles)
    eph.authority("lea", roles, admit=eph.JOB_MANAGERS)
    eph.authority("boss", roles)
    with pytest.raises(eph.Refused, match="not the administrator or a lead"):
        eph.authority("lex", roles, admit=eph.JOB_MANAGERS)
    with pytest.raises(eph.Refused, match="ephemeral agent cannot spawn"):
        eph.authority("eph-task-1a2b3c", lambda _n: "lead", admit=eph.JOB_MANAGERS)


def test_administrator_stop_reports_and_tears_down_and_retry_respawns(store, capsys):
    root, panes, launched = store
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-1") == cli.OK
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
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-1") == cli.REFUSED
    assert "governor admission could not be established" in capsys.readouterr().err
    assert not launched and eph.records(root) == []


# --- review round 1 (hammond, #406) --------------------------------------------

def test_unverifiable_hooks_still_deliver_and_spawn_succeeds(store, capsys):
    """macOS: hook verification is CANNOT_TELL on every launch (no /proc). The
    job was delivered, so the spawn is a success and the job goes LIVE."""
    root, panes, _launched = store
    panes.behaviour.update(rc=cli.CANNOT_TELL, delivered=True)
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-1") == cli.OK
    (rec,) = eph.records(root)
    assert rec["state"] == eph.LIVE


def test_an_undelivered_job_is_ended_not_left_idle(store, capsys):
    root, panes, _launched = store
    panes.behaviour.update(rc=cli.CANNOT_TELL, delivered=False)
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-1") == cli.CANNOT_TELL
    (rec,) = eph.records(root)
    assert rec["state"] == eph.DONE and rec["result"]["cause"] == "launch failed"
    assert not panes.exists(f"st-{rec['name']}")
    assert not (root / "crew" / f"{rec['name']}.json").exists()


def test_tend_during_launch_does_not_orphan_the_pane(store):
    """The race: a reap between "ledger + card written" and "pane up" used to
    mark the job died and drop its card, then the pane came up unsupervised."""
    root, panes, _launched = store
    panes.behaviour["during"] = lambda a: cli._spawn_reap(a)
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-1") == cli.OK
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
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-1") == cli.OK
    (rec,) = eph.records(root)
    monkeypatch.chdir(rec["workspace"])
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-2") == cli.REFUSED
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


def test_review_mode_none_waives_only_the_approval():
    """aegis-za4f.17 (Stiwi 11-27): a repo configured review_mode = "none"
    merges at green with no review; every other refusal still holds, and any
    mode but "none" still demands the non-author approval."""
    merge = {"name": "eph-merge-aaaaaa", "job": "merge", "state": eph.LIVE}
    assert eph.merge_gate(merge, HEAD, _pr(), [], GREEN, None, review_mode="none") == ""
    for mode in ("non-author", "", "nonee"):
        assert "no non-author APPROVE" in eph.merge_gate(
            merge, HEAD, _pr(), [], GREEN, None, review_mode=mode), mode
    changes = [{"user": {"login": "x"}, "state": "CHANGES_REQUESTED", "commit_id": HEAD}]
    cases = {
        "outside contribution": (_pr(author_association="CONTRIBUTOR"), [], GREEN, None),
        "draft": (_pr(draft=True), [], GREEN, None),
        "head moved": (_pr(head={"sha": "b" * 40}), [], GREEN, None),
        "requests changes": (_pr(), changes, GREEN, None),
        "signed verdict requests changes": (_pr(), [], GREEN, {"blocking": True}),
        "not green": (_pr(), [], [{"name": "ci", "status": "completed",
                                   "conclusion": "failure"}], None),
        "unproven": (_pr(), [], [], None),
    }
    for want, (pr, reviews, checks, verdict) in cases.items():
        assert want in eph.merge_gate(merge, HEAD, pr, reviews, checks, verdict,
                                      review_mode="none"), want


def test_review_mode_rows_fail_closed():
    """Missing fact, unknown value or conflict -> non-author; only a unanimous none waives."""
    f = eph.review_mode_from_rows
    assert f([{"mode": "none"}]) == "none"
    assert f([{"mode": "http://aegis.gastown.local/ontology/none"}]) == "none"
    assert f([{"mode": {"type": "literal", "value": "none"}}]) == "none"
    for rows in ([], None, [{"mode": "non-author"}], [{"mode": "off"}], [{}],
                 [{"mode": "none"}, {"mode": "non-author"}], "none"):
        assert f(rows) == "non-author", rows


def _timeout(*_a, **_k):
    raise TimeoutError("quipu did not answer")


@pytest.mark.parametrize("reader, merged", [
    (lambda *a, **k: [{"mode": "none"}], True),          # game / Forgejo repo
    (lambda *a, **k: [{"mode": "non-author"}], False),   # product repo, no review
    (lambda *a, **k: [], False),                         # missing fact
    (_timeout, False),                                   # query UNKNOWN
])
def test_guarded_merge_reads_the_repos_review_mode_from_quipu(store, reader, merged):
    root, _panes, _launched = store
    rec = _rec(root, job="merge", repo="o/n", pr=5, state=eph.LIVE)
    reads = {"repos/o/n/pulls/5": _pr(), "repos/o/n/pulls/5/reviews?per_page=100": [],
             f"repos/o/n/commits/{HEAD}/check-runs?per_page=100": {"check_runs": GREEN}}
    ran, asked = [], []

    class _R:
        returncode, stdout, stderr = 0, "", ""
    a = cli._parse_args(["--root", str(root), "agent", "spawn", "--merge", "--head", HEAD])
    a.root = root

    def read(root_, name, params, **k):
        asked.append((name, params))
        return reader(root_, name, params, **k)
    go = lambda: cli._spawn_merge(a, rec["name"], gh=lambda path: reads[path],  # noqa: E731
                                  run=lambda argv, **k: ran.append(argv) or _R(),
                                  review_reader=read)
    if merged:
        assert go() == cli.OK and len(ran) == 1
    else:
        with pytest.raises(eph.Refused, match="no non-author APPROVE"):
            go()
        assert ran == []
    assert asked == [(eph.REVIEW_MODE_QUERY, {"repo": "o/n"})]


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
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-1") == cli.OK
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
    assert _st(root, '--ephemeral', '--job', 'task', '--repo', 'o/n', '--item', 'it-other') == cli.REFUSED
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
    assert _st(root, '--ephemeral', '--job', 'task', '--repo', 'o/n', '--item', 'it-1') == cli.REFUSED
    assert 'unattended_uid_ready is false' in capsys.readouterr().err
    assert not launched and not eph.records(root)


def test_uid_readiness_must_be_boolean_and_cannot_replace_verified_identity(store, capsys):
    root, _, launched = store
    path = root / 'shantytown.toml'
    path.write_text('[ephemeral]\nunattended = true\nunattended_uid_ready = "yes"\n')
    with pytest.raises(config.ConfigError, match='unattended_uid_ready'):
        config.load(root)
    path.write_text('[ephemeral]\nunattended = true\nunattended_uid_ready = true\n')
    assert _st(root, '--ephemeral', '--job', 'task', '--repo', 'o/n', '--item', 'it-1', '--dry-run') == cli.REFUSED
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
    assert _st(root, '--ephemeral', '--job', 'task', '--repo', 'o/n', '--item', 'it-1') == cli.REFUSED
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
    assert _st(root, '--ephemeral', '--job', 'task', '--repo', 'o/n', '--item', 'it-legacy') == cli.OK
    rec, = eph.records(root)
    assert launched
    assert _st(root, '--stop', rec['name']) == cli.OK
    assert eph.read(root, rec['name'])['state'] == eph.DONE
    assert _st(root, '--ephemeral', '--job', 'task', '--repo', 'o/n', '--item', 'it-report') == cli.OK
    rec = next(r for r in eph.records(root) if r['state'] == eph.LIVE)
    monkeypatch.setenv('SHANTY_AGENT', rec['name'])
    monkeypatch.chdir(rec['workspace'])
    assert _st(root, '--report', '--verdict', 'done', '--dry-run') == cli.OK
    # Clearing the declaration cannot escape the workspace restriction.
    monkeypatch.delenv('SHANTY_AGENT', raising=False)
    assert _st(root, '--ephemeral', '--job', 'task', '--repo', 'o/n', '--item', 'it-nested') == cli.REFUSED


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
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-1") == cli.OK
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
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-1") == cli.REFUSED
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
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-1") == cli.OK
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
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-1") == cli.OK
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


def test_a_codex_task_job_gets_its_sandbox_profile_at_spawn(codex_store, monkeypatch, tmp_path):
    """aegis-za4f D1/D2: the spawner writes the narrow daemon profile into the
    job's own daemon home before launch, and records where."""
    import tempfile, shutil
    run = Path(tempfile.mkdtemp(prefix="st-", dir="/tmp"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(run))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    try:
        root, _panes, launched, _cfg, _seen = codex_store
        assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-1") == cli.OK
        (rec,) = eph.records(root)
        from shantytown.codex_daemon import runtime_home
        assert rec["codex_sandbox"] == str(runtime_home(rec["name"]) / eph.CODEX_SANDBOX_FILE)
        args = eph.codex_daemon_sandbox_args(rec["name"], runtime_home(rec["name"]))
        assert "sandbox_workspace_write.network_access=true" in args
        assert not any("danger-full-access" in x for x in args)
    finally:
        shutil.rmtree(run, True)


def test_a_task_job_whose_repo_resolves_no_checkout_is_refused_not_scratch(store, monkeypatch, capsys):
    """aegis-za4f D4: a named repo with no local checkout used to fall back to a
    scratch dir silently; the task job then had no source to edit."""
    root, _panes, launched = store
    monkeypatch.setattr(cli, "_resolve_repo", lambda name: root / "no-such-checkout")
    assert _st(root, "--ephemeral", "--job", "task", "--item", "it-1",
               "--repo", "o/n") == cli.REFUSED
    assert "resolved no local checkout" in capsys.readouterr().err
    assert launched == [] and eph.records(root) == []


def test_a_task_dry_run_previews_the_source_worktree_it_would_get(store, monkeypatch, capsys, tmp_path):
    root, _panes, launched = store
    checkout = tmp_path / "src"
    (checkout / ".git").mkdir(parents=True)
    monkeypatch.setattr(cli, "_resolve_repo", lambda name: checkout)
    assert _st(root, "--ephemeral", "--job", "task", "--item", "it-1", "--repo", "o/n", "-n") == cli.OK
    out = capsys.readouterr().out
    assert "Your worktree is a checkout of o/n" in out and "NO source worktree" not in out
    assert launched == [] and eph.records(root) == []


def test_a_task_job_uses_the_forges_canonical_repo_slug(store, monkeypatch, capsys, tmp_path):
    """aegis-za4f: eph-task-596fe4 was spawned with --repo scbrown/shantytown, a
    redirect to intigraph/shantytown. It did all its work, then `st repo pr`
    refused the non-canonical slug. Spawn now records the canonical one."""
    root, _panes, launched = store
    checkout = tmp_path / "src"
    (checkout / ".git").mkdir(parents=True)
    seen = []
    monkeypatch.setattr(cli, "_resolve_repo", lambda name: seen.append(name) or checkout)
    monkeypatch.setattr(cli, "_gh_json", lambda path: {"full_name": "neworg/n"}
                        if path == "repos/oldorg/n" else pytest.fail(path))
    assert _st(root, "--ephemeral", "--job", "task", "--item", "it-1", "--repo", "oldorg/n", "-n") == cli.OK
    out = capsys.readouterr()
    assert "it-1 — neworg/n" in out.out and "oldorg/n" not in out.out
    assert "now neworg/n on the forge" in out.err


def test_an_unreachable_forge_keeps_the_given_slug_and_says_so(store, monkeypatch, capsys, tmp_path):
    root, _panes, launched = store
    checkout = tmp_path / "src"
    (checkout / ".git").mkdir(parents=True)
    monkeypatch.setattr(cli, "_resolve_repo", lambda name: checkout)
    assert _st(root, "--ephemeral", "--job", "task", "--item", "it-1", "--repo", "o/n", "-n") == cli.OK
    out = capsys.readouterr()
    assert "it-1 — o/n" in out.out
    assert "could not confirm --repo o/n" in out.err


def test_review_jobs_are_not_canonicalized_here(store, monkeypatch):
    root, _panes, launched = store
    monkeypatch.setattr(cli, "_spawn_canonical_repo", lambda repo: pytest.fail("task jobs only"))
    _st(root, "--ephemeral", "--job", "review", "--item", "it-1", "--harness", "claude",
        "--repo", "o/n", "--pr", "3", "-n")


# --- aegis-maw: GitHub-only jobs refuse a foreign forge at admission ----------

def _checkout_with_origin(path, url):
    import subprocess
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "remote", "add", "origin", url], check=True)
    return path


def test_forge_refusal_names_the_forge_only_for_github_only_jobs():
    forgejo = "ssh://git@forge.local:2222/stiwi/goldblum.git"
    line = eph.forge_refusal("review", "stiwi/goldblum", forgejo)
    assert "hosted on forge.local, not GitHub" in line and "st go" in line
    assert eph.forge_refusal("merge", "stiwi/goldblum", forgejo)
    assert eph.forge_refusal("task", "stiwi/goldblum", forgejo) == ""
    assert eph.forge_refusal("review", "o/n", "git@github.com:o/n.git") == ""
    assert eph.forge_refusal("review", "o/n", "https://github.com/o/n") == ""
    assert eph.forge_refusal("review", "o/n", None) == ""      # cannot tell admits


def test_a_review_on_a_forgejo_repo_refuses_before_any_worktree_or_pane(
        store, monkeypatch, capsys, tmp_path):
    """sattler 2026-11-23: a review job on stiwi/goldblum#1218 spent a slot and
    ended BLOCKED on a 404. It now refuses at spawn, leaving nothing behind."""
    root, panes, launched = store
    checkout = _checkout_with_origin(tmp_path / "goldblum",
                                     "ssh://git@forge.local:2222/stiwi/goldblum.git")
    monkeypatch.setattr(cli, "_resolve_repo", lambda name: checkout)
    monkeypatch.setattr(eph, "provision_worktree",
                        lambda *a, **k: pytest.fail("no worktree may be cut"))
    rc = _st(root, "--ephemeral", "--job", "review", "--item", "it-1", "--harness", "claude",
             "--repo", "stiwi/goldblum", "--pr", "1218")
    assert rc == cli.REFUSED
    err = capsys.readouterr().err
    assert "refused: --repo stiwi/goldblum is hosted on forge.local, not GitHub" in err
    assert launched == [] and eph.records(root) == [] and eph.free_slots(root) == 1
    assert not (root / "crew").joinpath("eph-review").exists()
    assert [p.name for p in (root / "crew").iterdir()] == ["boss.json"]


def test_a_review_on_a_github_repo_still_spawns_dry_run(store, monkeypatch, capsys, tmp_path):
    root, _panes, launched = store
    checkout = _checkout_with_origin(tmp_path / "n", "git@github.com:o/n.git")
    monkeypatch.setattr(cli, "_resolve_repo", lambda name: checkout)
    assert _st(root, "--ephemeral", "--job", "review", "--item", "it-1", "--harness", "claude",
               "--repo", "o/n", "--pr", "3", "-n") == cli.OK
    assert "not GitHub" not in capsys.readouterr().err


def test_a_task_job_on_a_forgejo_repo_is_not_refused_by_the_forge_check(
        store, monkeypatch, capsys, tmp_path):
    root, _panes, launched = store
    checkout = _checkout_with_origin(tmp_path / "goldblum",
                                     "ssh://git@forge.local:2222/stiwi/goldblum.git")
    monkeypatch.setattr(cli, "_resolve_repo", lambda name: checkout)
    assert _st(root, "--ephemeral", "--job", "task", "--item", "it-1",
               "--repo", "stiwi/goldblum", "-n") == cli.OK
    assert "not GitHub" not in capsys.readouterr().err


# --- the spawn queue (aegis-cui) ----------------------------------------------

def _ticket(root, item, priority, at, tid):
    t = eph.ticket_for(eph.Request(job="task", item=item), harness="claude",
                       priority=priority, requester="boss", now=at, token=lambda: tid)
    eph.enqueue(root, t)
    return t


def _launch_as_ledger(root, t):
    """What a successful spawn does with a claimed ticket, in one lock step."""
    with eph.lock(root):
        _rec(root, item=t["item"], ticket=t["id"])
        eph.settle(root, t["id"])


def test_drain_order_is_priority_then_age(tmp_path):
    _ticket(tmp_path, "it-low", 2, NOW + 1, "0" * 11 + "1")
    _ticket(tmp_path, "it-p1-new", 1, NOW + 3, "0" * 11 + "2")
    _ticket(tmp_path, "it-p1-old", 1, NOW + 2, "0" * 11 + "3")
    _ticket(tmp_path, "it-unranked", None, NOW, "0" * 11 + "4")
    order = []
    while True:
        t, _ = eph.claim_next(tmp_path, cap=10, item_state=lambda i: "open", now=NOW + 5)
        if t is None:
            break
        order.append(t["item"])
        _launch_as_ledger(tmp_path, t)
    assert order == ["it-p1-old", "it-p1-new", "it-low", "it-unranked"]
    assert eph.tickets(tmp_path) == []


def test_a_full_pool_claims_nothing_and_the_ticket_waits(tmp_path):
    _rec(tmp_path, name="eph-task-000001")
    _ticket(tmp_path, "it-2", 1, NOW, "a" * 12)
    t, _ = eph.claim_next(tmp_path, cap=1, item_state=lambda i: "open", now=NOW)
    assert t is None and eph.tickets(tmp_path)[0]["state"] == eph.QUEUED


@pytest.mark.parametrize("state", ["closed", "missing"])
def test_a_closed_or_missing_items_ticket_is_dropped_not_launched(tmp_path, state):
    _ticket(tmp_path, "it-gone", 0, NOW, "b" * 12)
    _ticket(tmp_path, "it-open", 3, NOW, "c" * 12)
    t, notes = eph.claim_next(tmp_path, cap=10, now=NOW,
                              item_state=lambda i: state if i == "it-gone" else "open")
    assert t["item"] == "it-open"
    assert any(f"item it-gone is {state}" in n for n in notes)
    dropped = json.loads((eph.queue_dir(tmp_path) / "dropped" / f"q-{'b' * 12}.json").read_text())
    assert dropped["reason"] == f"item it-gone is {state}"
    assert [x["id"] for x in eph.tickets(tmp_path)] == [t["id"]]


def test_an_unreadable_item_keeps_its_ticket_and_launches_nothing(tmp_path):
    _ticket(tmp_path, "it-1", 0, NOW, "d" * 12)
    t, notes = eph.claim_next(tmp_path, cap=10, item_state=lambda i: "unknown", now=NOW)
    assert t is None and "kept queued" in notes[0]
    assert eph.tickets(tmp_path)[0]["state"] == eph.QUEUED


def test_a_crash_between_dequeue_and_launch_neither_loses_nor_double_launches(tmp_path):
    """Semantics (ephemeral.py, the spawn queue): exactly-once launch. The ledger
    record carries the ticket id and is written in the lock step that deletes
    the ticket; recovery reads the ledger before reviving a dead claim."""
    _ticket(tmp_path, "it-1", 0, NOW, "e" * 12)
    open_ = lambda i: "open"
    first, _ = eph.claim_next(tmp_path, cap=10, item_state=open_, now=NOW, pid=4242)
    # The claimer is alive (still launching): nobody else takes it.
    again, _ = eph.claim_next(tmp_path, cap=10, item_state=open_, now=NOW + 1,
                              pid_alive=lambda p: True)
    assert again is None
    # Crash BEFORE the ledger write: the claim is revived, not lost.
    revived, notes = eph.claim_next(tmp_path, cap=10, item_state=open_, now=NOW + 2,
                                    pid=4343, pid_alive=lambda p: False)
    assert revived["id"] == first["id"] and "back in the queue" in notes[0]
    # Crash AFTER the ledger write but before the ticket was deleted: the
    # ledger says it launched, so the ticket is settled and never relaunched.
    _rec(tmp_path, item="it-1", ticket=first["id"])
    after, notes = eph.claim_next(tmp_path, cap=10, item_state=open_, now=NOW + 3,
                                  pid_alive=lambda p: False)
    assert after is None and "not relaunched" in notes[0]
    assert eph.tickets(tmp_path) == []
    assert [r["ticket"] for r in eph.records(tmp_path)] == [first["id"]]


def test_over_cap_spawn_queues_lists_and_drains_on_job_end(store, monkeypatch, capsys):
    root, _panes, launched = store
    items = {"it-1": "open", "it-2": "open", "it-3": "closed"}
    monkeypatch.setattr(cli, "_spawn_item_state", lambda a, i: items.get(i, "missing"))
    drains = []
    def drain_now(r):
        drains.append(r)
        return cli.main(["--root", str(r), "agent", "spawn", "--drain"])
    monkeypatch.setattr(eph, "kick_drain", drain_now)
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-1") == cli.OK
    (first,) = eph.records(root)
    capsys.readouterr()
    # --dry-run says what would queue and writes nothing.
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-2", "--priority", "1",
               "--dry-run") == cli.OK
    assert "would queue task on it-2 (P1" in capsys.readouterr().out
    assert eph.tickets(root) == []
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-3", "--priority", "0") == cli.OK
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-2", "--priority", "1") == cli.OK
    out = capsys.readouterr().out
    assert out.count("QUEUED q-") == 2 and len(launched) == 1
    assert _st(root, "--list") == cli.OK
    listing = capsys.readouterr().out
    assert "queued #1  task   it-3" in listing and "queued #2  task   it-2" in listing
    assert _st(root, "--list", "--json") == cli.OK
    js = json.loads(capsys.readouterr().out)
    assert [j["item"] for j in js if j["state"] == "queued"] == ["it-3", "it-2"]
    # The job ends: its slot drains the queue. it-3 outranks it-2 but its item
    # is closed, so it is dropped and it-2 launches in the freed slot.
    assert _st(root, "--stop", first["name"]) == cli.OK
    assert drains and len(launched) == 2
    err = capsys.readouterr().err
    assert "item it-3 is closed" in err
    (second,) = eph.live(root)
    assert second["item"] == "it-2" and second["ticket"].startswith("q-")
    assert second["spawned_by"] == "boss"
    assert eph.tickets(root) == []


def test_a_drained_ticket_the_spawn_refuses_is_dropped_with_its_reason(store, monkeypatch, capsys):
    root, _panes, launched = store
    monkeypatch.setattr(cli, "_spawn_item_state", lambda a, i: "open")
    monkeypatch.setattr(eph, "kick_drain", lambda r: None)
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-1") == cli.OK
    (first,) = eph.records(root)
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-2") == cli.OK
    assert _st(root, "--stop", first["name"]) == cli.OK
    monkeypatch.setattr(cli, "_spawn_governor_refusal", lambda a, card: "governor: held")
    assert _st(root, "--drain") == cli.REFUSED
    assert "launch refused: governor: held" in capsys.readouterr().err
    assert eph.tickets(root) == [] and len(launched) == 1


def test_an_ephemeral_agent_cannot_drain_the_queue(store, monkeypatch, capsys):
    root, panes, _launched = store
    panes.verified_actor = "eph-task-abcdef"
    monkeypatch.setenv("SHANTY_AGENT", "eph-task-abcdef")
    assert _st(root, "--drain") == cli.REFUSED
    assert "cannot drain" in capsys.readouterr().err


# --- routing by harness and track (aegis-fye) -----------------------------------

def _tk(root, item, *, harness="claude", track=None, priority=2, at=NOW, tid):
    t = eph.ticket_for(eph.Request(job="task", item=item, track=track), harness=harness,
                       priority=priority, requester="boss", now=at, token=lambda: tid)
    eph.enqueue(root, t)
    return t


def _drain_all(root, **routing):
    order = []
    while True:
        with eph.lock(root):
            t, _ = eph.claim_next(root, item_state=lambda i: "open", now=NOW + 9, **routing)
        if t is None:
            return order
        order.append(t["item"])
        with eph.lock(root):
            _rec(root, item=t["item"], ticket=t["id"], harness=t["harness"],
                 track=t.get("track"))
            eph.settle(root, t["id"])


def test_config_reads_harness_caps_and_track_shares_and_refuses_bad_ones(tmp_path):
    toml = tmp_path / "shantytown.toml"
    toml.write_text("[ephemeral]\nmax_agents = 3\n")
    e = config.load(tmp_path).ephemeral
    # Nothing configured: no harness caps, shares off.
    assert e.max_agents_by_harness == {} and e.track_shares == {}
    assert eph.harness_cap(e, "codex") == 3
    toml.write_text("[ephemeral]\nmax_agents = 3\n[ephemeral.max_agents_by_harness]\ncodex = 1\n"
                    "[ephemeral.track_shares]\nops = 20\nshort-term = 15\nroadmap = 50\nbacklog = 15\n")
    e = config.load(tmp_path).ephemeral
    assert eph.harness_cap(e, "codex") == 1 and eph.harness_cap(e, "claude") == 3
    assert e.track_shares == eph.SUGGESTED_TRACK_SHARES
    for bad, why in (("[ephemeral.track_shares]\nroadmp = 50\n", "unknown key"),
                     ("[ephemeral.track_shares]\nops = -1\n", "integer >= 0"),
                     ("[ephemeral.track_shares]\nops = 0\n", "share > 0"),
                     ("[ephemeral.max_agents_by_harness]\ncodex = true\n", "integer >= 0")):
        toml.write_text("[ephemeral]\nmax_agents = 3\n" + bad)
        with pytest.raises(config.ConfigError, match=why):
            config.load(tmp_path)


def test_with_nothing_configured_drain_order_is_slice_one_exactly(tmp_path):
    """Regression: mixed harnesses and tracks, no caps or shares configured,
    must drain in plain priority-then-age order, as before aegis-fye."""
    specs = [("it-a", "codex", "backlog", 2, 1), ("it-b", "claude", "ops", 1, 3),
             ("it-c", "codex", None, 1, 2), ("it-d", "claude", "roadmap", None, 0),
             ("it-e", "claude", "short-term", 0, 4)]
    for n, (item, h, tr, p, at) in enumerate(specs):
        _tk(tmp_path, item, harness=h, track=tr, priority=p, at=NOW + at, tid=f"{n:012x}")
    expected = [t["item"] for t in eph.tickets(tmp_path)]     # slice 1's _order
    assert expected == ["it-e", "it-c", "it-b", "it-a", "it-d"]
    assert _drain_all(tmp_path, **eph.routing(_policy(max_agents=10))) == expected


def test_a_codex_ticket_never_launches_into_claude_capacity(tmp_path):
    policy = _policy(max_agents=3, max_agents_by_harness={"codex": 1})
    _rec(tmp_path, name="eph-task-c0dec1", harness="codex")
    # The codex ticket is the oldest and highest priority, and two host slots
    # are free: it still waits, and the claude ticket behind it launches.
    _tk(tmp_path, "it-codex", harness="codex", priority=0, at=NOW, tid="a" * 12)
    _tk(tmp_path, "it-claude", harness="claude", priority=3, at=NOW + 5, tid="b" * 12)
    assert _drain_all(tmp_path, **eph.routing(policy)) == ["it-claude"]
    (left,) = eph.tickets(tmp_path)
    assert left["item"] == "it-codex" and left["state"] == eph.QUEUED
    # A direct codex spawn is over ITS cap even with host room, so it queues.
    with pytest.raises(eph.OverCap, match="over codex cap: 1/1"):
        _rec(tmp_path, harness="codex", policy=policy)
    _rec(tmp_path, harness="claude", policy=policy)           # claude still has room
    # The codex job ends: now the codex ticket has a slot... but the host is
    # full (3/3 live), so it must wait for that too.
    rec = eph.read(tmp_path, "eph-task-c0dec1")
    eph.write(tmp_path, dict(rec, state=eph.DONE))
    assert _drain_all(tmp_path, **eph.routing(policy)) == ["it-codex"]


def test_a_harness_capped_at_zero_is_refused_not_queued(tmp_path):
    policy = _policy(max_agents=3, max_agents_by_harness={"codex": 0})
    with pytest.raises(eph.Refused, match="codex ephemeral spawning is off") as off:
        _rec(tmp_path, harness="codex", policy=policy)
    assert not isinstance(off.value, eph.OverCap)


def test_with_shares_configured_the_under_share_track_drains_first(tmp_path):
    shares = eph.SUGGESTED_TRACK_SHARES
    # Live: two roadmap jobs. roadmap is at 100% of live slots against a 50%
    # share; ops (20%) is the furthest below. An ops ticket of LOWER priority
    # and younger age goes first; without shares it would go last.
    _rec(tmp_path, name="eph-task-a00001", track="roadmap")
    _rec(tmp_path, name="eph-task-a00002", track="roadmap")
    _tk(tmp_path, "it-road", track="roadmap", priority=0, at=NOW, tid="1" * 12)
    _tk(tmp_path, "it-back", track="backlog", priority=1, at=NOW + 1, tid="2" * 12)
    _tk(tmp_path, "it-ops", track="ops", priority=3, at=NOW + 2, tid="3" * 12)
    live = eph.live(tmp_path)
    off = eph.route(eph.tickets(tmp_path), live, cap=10, harness_caps={}, shares={})
    assert [t["item"] for t in off] == ["it-road", "it-back", "it-ops"]
    on = eph.drain_plan(eph.tickets(tmp_path), live, cap=4, harness_caps={}, shares=shares)
    # ops first (20% under). Then with ops 1/3, backlog 0/3 is 15% under while
    # roadmap 2/3 is 17% over: backlog before the higher-priority roadmap.
    assert [t["item"] for t in on] == ["it-ops", "it-back"]
    assert _drain_all(tmp_path, cap=10, harness_caps={}, shares=shares) == [
        "it-ops", "it-back", "it-road"]


def test_list_shows_harness_and_track_on_tickets_and_live_jobs(store, capsys):
    root, _panes, launched = store
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-1", "--track", "ops") == cli.OK
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-2",
               "--harness", "codex", "--track", "backlog") == cli.OK
    capsys.readouterr()
    assert _st(root, "--list") == cli.OK
    out = capsys.readouterr().out
    assert "· claude · ops · " in out
    assert "it-2  codex  backlog  P" in out
    (live,) = eph.live(root)
    assert live["track"] == "ops"
    (t,) = eph.tickets(root)
    assert (t["harness"], t["track"]) == ("codex", "backlog")


def test_cli_codex_ticket_waits_while_claude_capacity_is_free(codex_store, monkeypatch, capsys):
    """The DONE demo: max_agents 2, codex capped at 1. One codex job live, a
    second codex spawn queues although a slot is free; a claude spawn takes it."""
    root, _panes, launched, _cfg, _seen = codex_store
    (root / "shantytown.toml").write_text(
        "[ephemeral]\nmax_agents = 2\nunattended = false\nrequire_verified_identity = true\n"
        "[ephemeral.max_agents_by_harness]\ncodex = 1\n")
    monkeypatch.setattr(cli, "_spawn_item_state", lambda a, i: "open")
    monkeypatch.setattr(eph, "kick_drain", lambda r: None)
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-1", "--harness", "codex") == cli.OK
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-2", "--harness", "codex") == cli.OK
    assert "over codex cap: 1/1" in capsys.readouterr().out
    assert len(launched) == 1
    assert _st(root, "--drain", "--dry-run") == cli.OK
    assert "would drain 0 of 1 queued ticket(s) into 1 free slot(s)" in capsys.readouterr().out
    assert _st(root, "--drain") == cli.OK
    assert len(launched) == 1 and eph.tickets(root)[0]["item"] == "it-2"
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-3", "--harness", "claude") == cli.OK
    assert len(launched) == 2 and {r["harness"] for r in eph.live(root)} == {"codex", "claude"}


def test_task_prompt_says_push_and_open_by_hand_when_repo_pr_fails():
    """A failed `st repo pr` must not strand committed work local-only."""
    task = eph._JOBS["task"]
    assert "If `st repo pr` refuses or fails" in task
    assert "git push -u origin HEAD" in task and "gh pr create" in task


# --- queue recovery (aegis-za4f.16) ---------------------------------------------
#
# q-ecb33cbe0cca (--checkout a path that did not exist) killed every drain that
# claimed it; each drain revived the dead claim, took it first, and died again,
# so nothing launched for ~4h behind one ticket.

def test_a_dead_claim_is_revived_once_then_dropped_visibly(tmp_path):
    _ticket(tmp_path, "it-bad", 0, NOW, "f" * 12)
    _ticket(tmp_path, "it-good", 3, NOW, "1" * 12)
    open_, dead = (lambda i: "open"), (lambda p: False)
    first, _ = eph.claim_next(tmp_path, cap=10, item_state=open_, now=NOW, pid=1)
    assert first["item"] == "it-bad"
    # The claimer died once: revived (and reclaimed: it is still first).
    again, notes = eph.claim_next(tmp_path, cap=10, item_state=open_, now=NOW + 1,
                                  pid=2, pid_alive=dead)
    assert again["item"] == "it-bad" and "back in the queue" in notes[0]
    # It died again: dropped with its reason, and the good ticket is claimed.
    nxt, notes = eph.claim_next(tmp_path, cap=10, item_state=open_, now=NOW + 2,
                                pid=3, pid_alive=dead)
    assert nxt["item"] == "it-good"
    assert any("claimer died before launch 2 times" in n for n in notes)
    (gone,) = eph.dropped(tmp_path, NOW + 3)
    assert gone["id"] == "q-" + "f" * 12
    line = eph.render_dropped([gone], NOW + 3)[0]
    assert "failed" in line and "claimer died" in line and "(launching)" not in line


def test_a_stale_claim_by_a_live_pid_is_also_recovered(tmp_path):
    _ticket(tmp_path, "it-1", 0, NOW, "2" * 12)
    eph.claim_next(tmp_path, cap=10, item_state=lambda i: "open", now=NOW, pid=1)
    t, notes = eph.claim_next(tmp_path, cap=10, item_state=lambda i: "open",
                              now=NOW + eph.LAUNCH_GRACE_S + 1, pid_alive=lambda p: True)
    assert t is not None and "back in the queue" in notes[0]


def _two_queued(store, monkeypatch, bad_item="it-bad"):
    root, panes, launched = store
    monkeypatch.setattr(cli, "_spawn_item_state", lambda a, i: "open")
    monkeypatch.setattr(eph, "kick_drain", lambda r: None)
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-1") == cli.OK
    (first,) = eph.records(root)
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", bad_item, "--priority", "0") == cli.OK
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-good", "--priority", "3") == cli.OK
    assert _st(root, "--stop", first["name"]) == cli.OK
    return root, panes, launched


def test_one_crashing_ticket_fails_and_the_drain_launches_the_next(store, monkeypatch, capsys):
    root, panes, launched = _two_queued(store, monkeypatch)

    real = cli._spawn_item_context

    def crash(a, item):
        # Before the ledger record, where the incident's launch died.
        if item == "it-bad":
            raise FileNotFoundError("/nonexistent/checkout")
        return real(a, item)
    monkeypatch.setattr(cli, "_spawn_item_context", crash)
    assert _st(root, "--drain") != cli.OK          # the crash is reported, not raised
    err = capsys.readouterr().err
    assert "launch crashed: FileNotFoundError" in err
    assert [r["item"] for r in eph.live(root)] == ["it-good"]
    assert eph.tickets(root) == []
    assert _st(root, "--list") == cli.OK
    listing = capsys.readouterr().out
    assert "failed" in listing and "it-bad" in listing and "(launching)" not in listing


def test_a_dead_claim_ahead_of_a_good_ticket_does_not_block_the_drain(store, monkeypatch, capsys):
    root, _panes, launched = _two_queued(store, monkeypatch)
    (bad,) = [t for t in eph.tickets(root) if t["item"] == "it-bad"]
    # Already revived once and its claimer dead again: the 4h incident's state.
    eph._put(root, dict(bad, state=eph.CLAIMED, claimed_by=999_999_999,
                        claimed_at=__import__("time").time(), recoveries=1))
    assert _st(root, "--drain") == cli.OK
    assert [r["item"] for r in eph.live(root)] == ["it-good"]
    assert "claimer died before launch" in capsys.readouterr().err


def test_a_missing_checkout_is_refused_at_queue_time(store, capsys, tmp_path):
    root, _panes, launched = store
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-1") == cli.OK
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-2",
               "--repo", "o/n", "--checkout", str(tmp_path / "nonexistent")) == cli.REFUSED
    assert "does not exist" in capsys.readouterr().err
    assert eph.tickets(root) == []


def test_a_checkout_without_the_repos_remote_is_refused(store, capsys, tmp_path):
    root, _panes, launched = store
    plain = tmp_path / "plain"
    plain.mkdir()
    other = _checkout_with_origin(tmp_path / "other", "git@github.com:o/other.git")
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-2",
               "--checkout", str(plain)) == cli.REFUSED
    assert "not a git checkout" in capsys.readouterr().err
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-2",
               "--repo", "o/n", "--checkout", str(other)) == cli.REFUSED
    assert "no remote for --repo o/n" in capsys.readouterr().err
    assert launched == []


def test_checkout_refusal_admits_a_matching_remote_on_any_host():
    ok = eph.checkout_refusal("/c", "Stiwi/Goldblum", exists=True,
                              remotes=["ssh://git@forge.local:2222/stiwi/goldblum.git"])
    assert ok == ""
    assert eph.checkout_refusal(None, "o/n", exists=False, remotes=None) == ""
    assert "does not exist" in eph.checkout_refusal("/c", "o/n", exists=False, remotes=None)



# --- aegis-za4f.16.1: a pre-move remote URL still names the moved repo ---------

MOVED = {"scbrown/tambo": "intigraph/tambo", "intigraph/tambo": "intigraph/tambo",
         "scbrown/bobbin": "intigraph/bobbin", "intigraph/bobbin": "intigraph/bobbin",
         "o/other": "o/other"}


def test_a_pre_move_remote_is_admitted_for_the_moved_repo():
    canon = MOVED.get
    for repo in ("intigraph/tambo", "scbrown/tambo", "Intigraph/Tambo"):
        assert eph.checkout_refusal("/c", repo, exists=True, canonical=canon,
                                    remotes=["git@github.com:scbrown/tambo.git"]) == "", repo
    assert eph.checkout_refusal("/c", "intigraph/bobbin", exists=True, canonical=canon,
                                remotes=["https://github.com/scbrown/bobbin"]) == ""


def test_a_remote_for_another_repo_is_still_refused_after_canonicalizing():
    asked = []
    def canon(slug):
        asked.append(slug)
        return MOVED.get(slug)
    why = eph.checkout_refusal("/c", "intigraph/tambo", exists=True, canonical=canon,
                               remotes=["git@github.com:o/other.git"])
    assert "no remote for --repo intigraph/tambo" in why and "could not confirm" not in why
    assert "o/other" in asked
    # A non-GitHub remote is never sent to GitHub's redirect map.
    asked.clear()
    assert eph.checkout_refusal("/c", "intigraph/tambo", exists=True, canonical=canon,
                                remotes=["ssh://git@forge.local/scbrown/tambo.git"]) != ""
    assert "scbrown/tambo" not in asked
    assert "does not exist" in eph.checkout_refusal("/c", "intigraph/tambo", exists=False,
                                                    remotes=None, canonical=canon)


def test_an_unanswering_forge_refuses_and_says_it_could_not_confirm():
    why = eph.checkout_refusal("/c", "intigraph/tambo", exists=True, canonical=lambda s: None,
                               remotes=["git@github.com:scbrown/tambo.git"])
    assert "could not confirm where git@github.com:scbrown/tambo.git points" in why


def test_a_matching_remote_never_asks_the_forge():
    assert eph.checkout_refusal("/c", "intigraph/tambo", exists=True,
                                canonical=lambda s: pytest.fail(s),
                                remotes=["git@github.com:intigraph/tambo.git"]) == ""


def test_spawn_admits_a_checkout_whose_origin_predates_the_move(store, monkeypatch, capsys, tmp_path):
    """The live probe: --repo scbrown/tambo canonicalizes to intigraph/tambo and
    ~/gt/caboodle's origin is git@github.com:scbrown/tambo.git."""
    root, _panes, launched = store
    caboodle = _checkout_with_origin(tmp_path / "caboodle", "git@github.com:scbrown/tambo.git")
    monkeypatch.setattr(cli, "_gh_json", lambda path: {"full_name": MOVED[path.removeprefix("repos/")]})
    assert _st(root, "--ephemeral", "--job", "task", "--item", "it-1", "--repo", "scbrown/tambo",
               "--checkout", str(caboodle), "-n") == cli.OK
    out = capsys.readouterr()
    assert "no remote for" not in out.err and "intigraph/tambo" in out.out
    other = _checkout_with_origin(tmp_path / "other", "git@github.com:o/other.git")
    assert _st(root, "--ephemeral", "--job", "task", "--item", "it-2", "--repo", "scbrown/tambo",
               "--checkout", str(other), "-n") == cli.REFUSED
    assert "no remote for --repo intigraph/tambo" in capsys.readouterr().err

def test_stop_cancels_a_queued_ticket_reversibly(store, monkeypatch, capsys):
    root, _panes, launched = store
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-1") == cli.OK
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-2") == cli.OK
    (t,) = eph.tickets(root)
    eph._put(root, dict(t, state=eph.CLAIMED, claimed_by=1, claimed_at=NOW))
    capsys.readouterr()
    assert _st(root, "--stop", t["id"]) == cli.OK
    assert f"cancelled {t['id']}" in capsys.readouterr().out
    assert eph.tickets(root) == []
    assert _st(root, "--list") == cli.OK
    assert t["id"] not in capsys.readouterr().out
    kept = eph.removed_dir(root) / f"{t['id']}.json"
    assert json.loads(kept.read_text())["state"] == eph.QUEUED
    # Reversible: moving the file back requeues it, unclaimed.
    kept.rename(eph.queue_dir(root) / kept.name)
    (back,) = eph.tickets(root)
    assert back["id"] == t["id"] and back["state"] == eph.QUEUED
    # A ticket not in the queue is refused, not silently "cancelled".
    assert _st(root, "--stop", "q-" + "0" * 12) == cli.REFUSED

# --- aegis-za4f.15: a task job without --repo is refused at spawn -------------
# eph-task-9a5fba (za4f.15), 72e750 (xc7) and 2g7f were each spawned with no
# --repo, got a scratch dir with no source, and spent their whole slot finding
# out. The refusal comes before the request is built, so it holds over cap too.

def _no_ticket_files(root):
    q = eph.queue_dir(root)
    return not q.exists() or not any(q.iterdir())


def test_a_task_job_without_repo_is_refused_under_cap(store, capsys):
    root, _panes, launched = store
    assert _st(root, "--ephemeral", "--job", "task", "--item", "it-1") == cli.REFUSED
    assert "a task job needs --repo OWNER/NAME" in capsys.readouterr().err
    assert launched == [] and eph.records(root) == []
    assert eph.tickets(root) == [] and _no_ticket_files(root)


def test_a_task_job_without_repo_is_refused_over_cap_and_queues_nothing(store, capsys):
    root, _panes, launched = store
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-1") == cli.OK
    assert len(launched) == 1  # max_agents = 1: the next spawn is over cap
    capsys.readouterr()
    assert _st(root, "--ephemeral", "--job", "task", "--item", "it-2") == cli.REFUSED
    out = capsys.readouterr()
    assert "a task job needs --repo" in out.err and "QUEUED" not in out.out
    assert eph.tickets(root) == [] and _no_ticket_files(root)
    # The same spawn WITH --repo still queues exactly as before.
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-2") == cli.OK
    assert "QUEUED q-" in capsys.readouterr().out
    (t,) = eph.tickets(root)
    assert t["item"] == "it-2" and t["repo"] == "o/n"


def test_a_task_job_with_checkout_but_no_repo_is_refused(store, capsys, tmp_path):
    root, _panes, launched = store
    assert _st(root, "--ephemeral", "--job", "task", "--item", "it-1",
               "--checkout", str(tmp_path / "fixture-src")) == cli.REFUSED
    err = capsys.readouterr().err
    assert "a task job needs --repo" in err and "--checkout without --repo" in err
    assert launched == [] and eph.records(root) == [] and eph.tickets(root) == []


@pytest.mark.parametrize("job", ["review", "merge", "triage"])
def test_other_jobs_without_repo_are_not_held_to_the_task_rule(store, capsys, job):
    root, _panes, _launched = store
    _st(root, "--ephemeral", "--job", job, "--item", "it-1", "--harness", "claude", "-n")
    assert "a task job needs --repo" not in capsys.readouterr().err
