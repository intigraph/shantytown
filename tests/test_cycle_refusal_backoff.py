"""A refused cycle request is retried on an interval, not on every pass (aegis-qc2).

Measured 2026-10-16: four requests refused on dirty trees were re-served on all
36 tend passes in three hours, 10-50s each, and spent the 120s sweep budget
before the later sweeps (the deferral sweep among them) could start. The request
stays pending either way; only the re-serve is spaced out.
"""
import time
import pytest

from shantytown import cli, cycle


def _tend_world(tmp_path, monkeypatch):
    from tests.test_tend import _Panes, _roster
    _roster(tmp_path, {"worker": {"role": "worker", "pane": "p-worker"}})
    monkeypatch.setattr(cli, "Tmux",
                        lambda *_a, **_k: _Panes(live={"p-worker"}))


def _served(tmp_path, monkeypatch):
    from tests.test_tend import _Args
    seen = []
    monkeypatch.setattr(cli, "_cmd_cycle", lambda ns: seen.append(ns.agent) or cli.OK)
    cli._tend_once(_Args(tmp_path, backend="files"))
    return seen.count("worker")


def test_a_fresh_request_is_served(tmp_path, monkeypatch):
    _tend_world(tmp_path, monkeypatch)
    cycle.Requests(tmp_path).request("worker", "ckpt")
    assert _served(tmp_path, monkeypatch) == 1


def test_a_recent_refusal_is_not_re_served_and_stays_pending(tmp_path, monkeypatch):
    _tend_world(tmp_path, monkeypatch)
    r = cycle.Requests(tmp_path)
    r.request("worker", "ckpt")
    assert r.mark_refused("worker", "work would be lost or stranded")
    assert _served(tmp_path, monkeypatch) == 0
    # Never dropped: the agent still has its request and its refusal reason.
    rec = cycle.Requests(tmp_path).pending()["worker"]
    assert rec["checkpoint"] == "ckpt"
    assert rec["refused"]["reason"].startswith("work would be lost")


def test_a_refusal_past_the_interval_is_retried(tmp_path, monkeypatch):
    _tend_world(tmp_path, monkeypatch)
    r = cycle.Requests(tmp_path)
    r.request("worker", "ckpt")
    r.mark_refused("worker", "dirty tree")
    data = r._load()
    data["worker"]["refused"]["at"] = time.time() - cli._CYCLE_REFUSED_RETRY_S - 1
    r._save(data)
    assert _served(tmp_path, monkeypatch) == 1


def test_a_new_request_after_a_refusal_is_served_immediately(tmp_path, monkeypatch):
    _tend_world(tmp_path, monkeypatch)
    r = cycle.Requests(tmp_path)
    r.request("worker", "ckpt")
    r.mark_refused("worker", "dirty tree")
    r.request("worker", "ckpt after cleaning the tree")
    assert _served(tmp_path, monkeypatch) == 1


def test_an_unreadable_refusal_time_fails_toward_serving():
    for refused in ({"reason": "x"}, {"reason": "x", "at": "soon"},
                    {"reason": "x", "at": True}, "legacy"):
        assert cli._refusal_backing_off({"refused": refused}) is False
    assert cli._refusal_backing_off({"refused": None}) is False
    # A clock that moved backwards is not "recent": retry rather than stall.
    assert cli._refusal_backing_off({"refused": {"at": time.time() + 3600}}) is False
    assert cli._refusal_backing_off({"refused": {"at": time.time()}}) is True


def _serve_with_pane(tmp_path, monkeypatch, screen):
    """Drive the real served path; record whether the costly tree guard ran."""
    from tests.test_tend import _Args, _Panes, _roster
    _roster(tmp_path, {"worker": {"role": "worker", "pane": "p-worker"}})
    monkeypatch.setattr(cli, "Tmux",
                        lambda *_a, **_k: _Panes(screens={"p-worker": screen}))
    cycle.Requests(tmp_path).request("worker", "ckpt")
    walked = []

    def trees(*a, **k):
        walked.append(1)
        raise RuntimeError("stop after the guard is reached")
    monkeypatch.setattr(cli, "_agent_trees", trees)
    request = cycle.Requests(tmp_path).pending()["worker"]
    try:
        rc = cli._serve_cycle_request(_Args(tmp_path, backend="files"), "worker", request)
    except RuntimeError:
        rc = None
    return rc, walked


def test_a_busy_pane_refuses_before_the_costly_guard(tmp_path, monkeypatch):
    """aegis-qc2: the locked re-check refused a busy pane only after the network
    fetch and tree walk. The same refusal now comes first; the request stays."""
    from tests.test_tend import BUSY
    rc, walked = _serve_with_pane(tmp_path, monkeypatch, BUSY)
    assert rc == cli.REFUSED and walked == []
    assert "worker" in cycle.Requests(tmp_path).pending()


def test_an_idle_pane_still_reaches_the_guard(tmp_path, monkeypatch):
    from tests.test_tend import IDLE
    _, walked = _serve_with_pane(tmp_path, monkeypatch, IDLE)
    assert walked == [1]


@pytest.mark.parametrize("account_switch,expected_walk", [(False, False), (True, True)])
def test_limited_boundary_keeps_account_switch_exception(
        tmp_path, monkeypatch, account_switch, expected_walk):
    """The early observation preserves the locked check's account-switch exception."""
    from types import SimpleNamespace
    from tests.test_tend import _Args, _Panes, _roster, IDLE
    _roster(tmp_path, {"worker": {"role": "worker", "pane": "p-worker"}})
    monkeypatch.setattr(cli, "Tmux",
                        lambda *_a, **_k: _Panes(screens={"p-worker": IDLE}))
    monkeypatch.setattr(cli, "_cycle_stop_refusal", lambda *_a: "")
    monkeypatch.setattr(cli, "_runtime",
                        lambda *_a: SimpleNamespace(shows_ready_ui=lambda _p: True))
    monkeypatch.setattr(cli.triage_mod, "work_state",
                        lambda *_a, **_k: cli.triage_mod.LIMITED)
    monkeypatch.setattr(cli, "asks_a_question", lambda *_a: False)
    monkeypatch.setattr(cli, "auth_expired", lambda *_a: False)
    monkeypatch.setattr(cli, "limit_reached", lambda *_a: True)
    monkeypatch.setattr(cli, "_cycle_input_empty", lambda *_a: True)
    monkeypatch.setattr(cli.harness_mod, "name_for", lambda *_a: "claude")
    monkeypatch.setattr(cli.notify_mod, "unattended_shell_block", lambda *_a, **_k: "")
    walked = []

    def trees(*_a, **_k):
        walked.append(1)
        raise RuntimeError("guard reached")
    monkeypatch.setattr(cli, "_agent_trees", trees)
    args = _Args(tmp_path, backend="files", agent="worker", self_=False,
                 serve_request=False, _automatic_cycle=True,
                 _account_card=object() if account_switch else None)
    try:
        cli._cmd_cycle(args)
    except RuntimeError as exc:
        assert str(exc) == "guard reached"
    assert bool(walked) == expected_walk
