"""Ephemeral pool management (aegis-za4f.3): resize, pause, drain, per-job
concurrency and the queue TTL. Each check here is also shown saying no."""
from __future__ import annotations

import json

import pytest

from shantytown import cli, config
from shantytown import ephemeral as eph

from test_ephemeral import NOW, _rec, _st, _ticket, store  # noqa: F401


# --- pool size ------------------------------------------------------------------

def test_a_runtime_pool_size_replaces_the_config_cap(store, monkeypatch, capsys):
    root, _panes, launched = store                 # config max_agents = 1
    monkeypatch.setattr(eph, "kick_drain", lambda r: None)
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-1") == cli.OK
    # At the config cap the second spawn queues ...
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-2") == cli.OK
    assert "QUEUED" in capsys.readouterr().out and len(launched) == 1
    # ... and after a resize to 2 the third launches straight away.
    assert _st(root, "--pool", "size", "2") == cli.OK
    assert eph.pool_state(root)["size"] == 2
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-3") == cli.OK
    assert len(launched) == 2
    assert _st(root, "--pool", "status") == cli.OK
    out = capsys.readouterr().out
    assert "pool: open; 2/2 slot(s) live (set by boss, config 1); 1 queued" in out
    # `size config` returns to the toml cap.
    assert _st(root, "--pool", "size", "config") == cli.OK
    assert eph.pool_state(root)["size"] is None


@pytest.mark.parametrize("bad", ["0", "-1", "two"])
def test_pool_size_refuses_a_non_positive_size(store, capsys, bad):
    root, _panes, _launched = store
    assert _st(root, "--pool", "size", bad) == cli.REFUSED
    assert "integer >= 1" in capsys.readouterr().err
    assert eph.pool_state(root)["size"] is None


def test_a_runtime_size_cannot_switch_on_a_host_whose_config_is_off(tmp_path):
    policy = config.Ephemeral(max_agents=0)
    assert eph.pooled(policy, {"size": 5}).max_agents == 0


def test_a_corrupt_pool_file_falls_back_to_config_never_wedges(tmp_path):
    eph.pool_path(tmp_path).parent.mkdir(parents=True)
    eph.pool_path(tmp_path).write_text("{not json")
    assert eph.pool_state(tmp_path) == {"size": None, "paused": False, "draining": False}


def test_a_worker_cannot_change_the_pool_but_can_read_it(store, monkeypatch, capsys):
    root, panes, _launched = store
    (root / "crew" / "wkr.json").write_text(json.dumps({"role": "worker", "pane": "st-wkr"}))
    panes.verified_actor = "wkr"
    monkeypatch.setenv("SHANTY_AGENT", "wkr")
    assert _st(root, "--pool", "pause") == cli.REFUSED
    assert eph.pool_state(root)["paused"] is False
    assert _st(root, "--pool", "status") == cli.OK
    assert "pool: open" in capsys.readouterr().out


# --- pause and drain --------------------------------------------------------------

def test_pause_queues_fresh_spawns_and_resume_launches_them(store, monkeypatch, capsys):
    root, _panes, launched = store
    monkeypatch.setattr(cli, "_spawn_item_state", lambda a, i: "open")
    kicks = []
    def drain_now(r):
        kicks.append(r)
        return cli.main(["--root", str(r), "agent", "spawn", "--drain"])
    monkeypatch.setattr(eph, "kick_drain", drain_now)
    assert _st(root, "--pool", "pause") == cli.OK
    # A free slot, but paused: the spawn is held as a ticket, not refused.
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-1") == cli.OK
    assert "pool is paused by boss" in capsys.readouterr().out
    assert launched == [] and len(eph.tickets(root)) == 1
    assert eph.free_slots(root) == 0
    # A drain while paused launches nothing and keeps the ticket.
    assert _st(root, "--drain") == cli.OK
    assert launched == [] and len(eph.tickets(root)) == 1
    assert _st(root, "--pool", "resume") == cli.OK
    assert kicks and len(launched) == 1 and eph.tickets(root) == []


def test_drain_refuses_new_work_and_holds_the_queue(store, monkeypatch, capsys):
    root, _panes, launched = store
    monkeypatch.setattr(eph, "kick_drain", lambda r: None)
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-1") == cli.OK
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-2") == cli.OK  # queued
    assert _st(root, "--pool", "drain") == cli.OK
    capsys.readouterr()
    assert _st(root, "--ephemeral", "--job", "task", "--repo", "o/n", "--item", "it-3") == cli.REFUSED
    assert "pool is draining" in capsys.readouterr().err
    assert [t["item"] for t in eph.tickets(root)] == ["it-2"]
    (job,) = eph.live(root)
    assert _st(root, "--stop", job["name"]) == cli.OK
    assert len(launched) == 1                      # nothing launched behind it
    assert _st(root, "--pool", "status") == cli.OK
    out = capsys.readouterr().out
    assert "pool: draining; 0/1 slot(s) live" in out and "drained (no live jobs)" in out


def test_claim_next_launches_nothing_while_paused(tmp_path):
    _ticket(tmp_path, "it-1", 0, NOW, "a" * 12)
    with eph.lock(tmp_path):
        eph.set_pool(tmp_path, actor="boss", now=NOW, paused=True)
    t, notes = eph.claim_next(tmp_path, cap=10, item_state=lambda i: "open", now=NOW)
    assert t is None and "paused" in notes[-1]
    with eph.lock(tmp_path):
        eph.set_pool(tmp_path, actor="boss", now=NOW, paused=False)
    t, _ = eph.claim_next(tmp_path, cap=10, item_state=lambda i: "open", now=NOW)
    assert t is not None and t["item"] == "it-1"


# --- per-job concurrency -------------------------------------------------------------

def test_per_job_concurrency_queues_over_its_own_cap(tmp_path):
    policy = config.Ephemeral(max_agents=10, limits={"review": {"max_concurrent": 1}})
    _rec(tmp_path, job="review", repo="o/r", pr=1, policy=policy)
    req = eph.Request(job="review", item="it-2", repo="o/r", pr=2)
    with pytest.raises(eph.OverCap, match="over review concurrency: 1/1"):
        eph.plan(req, root=tmp_path, policy=policy, actor="boss", administrator="boss",
                 host=None, now=NOW, role_of=lambda n: "administrator")
    # Another job type is not held by review's cap.
    eph.plan(eph.Request(job="task", item="it-3"), root=tmp_path, policy=policy,
             actor="boss", administrator="boss", host=None, now=NOW,
             role_of=lambda n: "administrator")


def test_the_drain_skips_a_ticket_whose_job_is_at_its_concurrency(tmp_path):
    policy = config.Ephemeral(max_agents=10, limits={"task": {"max_concurrent": 1}})
    _rec(tmp_path, job="task", policy=policy)
    _ticket(tmp_path, "it-2", 0, NOW, "b" * 12)
    r = eph.routing(policy)
    assert r["job_caps"] == {"task": 1}
    t, _ = eph.claim_next(tmp_path, now=NOW, item_state=lambda i: "open", **r)
    assert t is None
    t, _ = eph.claim_next(tmp_path, now=NOW, item_state=lambda i: "open",
                          **dict(r, job_caps={}))
    assert t is not None


def test_config_reads_max_concurrent_and_queue_ttl(tmp_path):
    (tmp_path / "shantytown.toml").write_text(
        "[ephemeral]\nqueue_ttl_minutes = 30\n[ephemeral.limits.review]\nmax_concurrent = 2\n")
    cfg = config.load(tmp_path)
    assert cfg.ephemeral.queue_ttl_minutes == 30
    assert cfg.ephemeral.limits["review"]["max_concurrent"] == 2
    (tmp_path / "shantytown.toml").write_text(
        "[ephemeral.limits.review]\nmax_concurrent = 0\n")
    with pytest.raises(config.ConfigError, match="max_concurrent must be an integer >= 1"):
        config.load(tmp_path)


# --- queue TTL ----------------------------------------------------------------------

def test_an_overdue_ticket_is_reported_once_and_stays_queued(tmp_path):
    _ticket(tmp_path, "it-old", 1, NOW, "c" * 12)
    _ticket(tmp_path, "it-new", 1, NOW + 3500, "d" * 12)
    events, comments = [], []
    later = NOW + 3601
    with eph.lock(tmp_path):
        lines = eph.report_overdue(tmp_path, "boss", 60, later,
                                   persist_event=lambda **kw: events.append(kw),
                                   comment=lambda i, b: comments.append((i, b)))
    assert len(lines) == 1 and "reported" in lines[0]
    assert events[0]["to"] == "boss" and events[0]["item"] == "it-old"
    assert comments[0][0] == "it-old" and "past the 60m queue TTL" in comments[0][1]
    assert {t["item"] for t in eph.tickets(tmp_path)} == {"it-old", "it-new"}
    assert "OVERDUE" in eph.render_tickets(eph.tickets(tmp_path), later)[0]
    with eph.lock(tmp_path):
        assert eph.report_overdue(tmp_path, "boss", 60, later + 60,
                                  persist_event=lambda **kw: events.append(kw),
                                  comment=lambda i, b: comments.append((i, b))) == []
    assert len(events) == 1


def test_an_overdue_ticket_nobody_heard_about_is_retried_never_silent(tmp_path):
    _ticket(tmp_path, "it-old", 1, NOW, "e" * 12)
    def down(*a, **kw):
        raise OSError("down")
    with eph.lock(tmp_path):
        lines = eph.report_overdue(tmp_path, "boss", 60, NOW + 7200,
                                   persist_event=down, comment=down)
    assert "NOT reported, retried next sweep" in lines[0]
    assert eph.overdue(tmp_path, 60, NOW + 7200)          # still due a report


def test_a_ttl_of_zero_reports_nothing(tmp_path):
    _ticket(tmp_path, "it-old", 1, NOW - 10 ** 6, "f" * 12)
    assert eph.overdue(tmp_path, 0, NOW) == []


def test_the_tend_reap_sweep_reports_an_overdue_ticket(store, monkeypatch, capsys):
    root, _panes, _launched = store
    (root / "shantytown.toml").write_text(
        "[ephemeral]\nmax_agents = 1\nqueue_ttl_minutes = 1\n")
    comments = []
    monkeypatch.setattr(cli, "_spawn_item_comment",
                        lambda a: lambda i, b: comments.append((i, b)))
    t = _ticket(root, "it-1", 1, 1.0, "1" * 12)          # enqueued near the epoch
    assert _st(root, "--reap") == cli.OK
    assert f"{t['id']} past queue TTL (1m): reported" in capsys.readouterr().err
    assert comments and comments[0][0] == "it-1"
    assert eph.read_ticket(root, t["id"])["overdue_reported_at"]
