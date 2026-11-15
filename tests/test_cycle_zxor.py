"""aegis-zxor: an accepted in-place self-cycle never completed, and nothing could
withdraw the request. Measured 2026-11-11 on a macOS host (logs/self-cycle-<agent>.log):
four soft clears succeeded, then one send hit tmux copy-mode (PaneInMode, nothing
typed). The "clear sent" marker had been persisted before the send and was kept,
so every later pass only observed a clear that could never arrive. On a Linux host the
same verb failed "clear session baseline unavailable (ValueError)" with no reason.

Every test drives the real functions with fixture panes and a temp root; no real
pane, hook, tmux or agent is touched.
"""
import argparse
import json
import os
import time

import pytest

from shantytown import cli, cycle, soft_cycle, session_anchor
from shantytown import context_hint as ch, stop_policy
from shantytown.notify import CycleBlockedNotifier
from shantytown.protocols import Agent
from shantytown.tmux import PaneInMode

from tests.test_cycle import _Panes, _Reg


def hook(root, session="old", transcript="old.jsonl", at=None, agent="worker"):
    path = root / "context_budget" / f"{agent}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(dict(payload=dict(session_id=session,
        transcript_path=str(transcript)), at=time.time() if at is None else at)))


def soft_world(monkeypatch):
    monkeypatch.setattr(cli, "_capture_history_before_kill", lambda *a: None)
    monkeypatch.setattr(cli, "_CLEAR_SETTLE_S", 0.01)
    monkeypatch.setattr(cli, "_CLEAR_POLL_S", 0)
    monkeypatch.setattr(cli.triage_mod, "mid_flight", lambda _: False)
    monkeypatch.setattr(cli.harness_mod, "clear_command_for", lambda *a: "/clear")
    monkeypatch.setattr(cli.harness_mod, "bypass_intact", lambda *a: True)
    return argparse.Namespace(shows_ready_ui=lambda _: True)


class Pane:
    def __init__(self, in_mode=False):
        self.in_mode, self.sent = in_mode, []

    def send(self, pane, text):
        if self.in_mode:
            raise PaneInMode(f"pane {pane} is in a tmux mode: NOT DELIVERED.")
        self.sent.append(text)

    def capture(self, pane, attrs=False):
        return "ready"


# --- 1. a refused-before-typing send must not leave a marker -------------------

def test_copy_mode_send_withdraws_marker_and_next_pass_sends(tmp_path, monkeypatch, capsys):
    runtime = soft_world(monkeypatch)
    hook(tmp_path)
    cycle.Requests(tmp_path).request("worker", "checkpoint")
    args, card = argparse.Namespace(root=tmp_path), Agent(name="worker", dangerous=False)
    pane = Pane(in_mode=True)
    assert not cli._cycle_soft(args, card, "worker", "p", pane, runtime)
    err = capsys.readouterr().err
    assert "copy-mode" in err and "nothing was typed" in err
    assert not soft_cycle.pending(tmp_path, "worker"), "no clear was typed; none to observe"
    assert cycle.Requests(tmp_path).pending()["worker"], "the request still waits"
    pane.in_mode = False
    assert not cli._cycle_soft(args, card, "worker", "p", pane, runtime)
    assert pane.sent == ["/clear"], "the next pass must actually send the clear"
    hook(tmp_path, "new", "new.jsonl")
    assert cli._cycle_soft(args, card, "worker", "p", pane, runtime)
    assert pane.sent == ["/clear"]


def test_CONTROL_an_ambiguous_send_failure_still_retains_the_marker(tmp_path, monkeypatch):
    """Only PaneInMode is proven untyped. Any other failure may have typed the key."""
    runtime = soft_world(monkeypatch)
    hook(tmp_path)
    cycle.Requests(tmp_path).request("worker", "checkpoint")

    class Broken(Pane):
        def send(self, pane, text):
            raise RuntimeError("tmux went away mid-send")
    assert not cli._cycle_soft(argparse.Namespace(root=tmp_path),
        Agent(name="worker", dangerous=False), "worker", "p", Broken(), runtime)
    assert soft_cycle.pending(tmp_path, "worker")


# --- 2. a marker no current request owns is withdrawn, never "confirmed" --------

def test_unowned_marker_is_withdrawn_at_plan_time(tmp_path, capsys):
    """The hammond state: marker from 17:03Z, ledger entry hand-removed, and a
    different live session that would have 'confirmed' a clear st never sent."""
    hook(tmp_path)
    soft_cycle.begin(tmp_path, "worker")
    hook(tmp_path, "manual-clear", "manual.jsonl")
    assert soft_cycle.confirmed(tmp_path, "worker",
        json.loads((tmp_path / "cycle-soft/worker.json").read_text())), \
        "precondition: the stale marker WOULD confirm"
    plan = cli._cycle_plan(argparse.Namespace(root=tmp_path), Agent(name="worker"),
                           "", _Panes({}), None)
    assert not soft_cycle.pending(tmp_path, "worker")
    assert "observe" not in plan.render()
    assert "withdrew" in capsys.readouterr().err


def test_marker_older_than_the_current_request_is_withdrawn(tmp_path, monkeypatch):
    hook(tmp_path)
    soft_cycle.begin(tmp_path, "worker")
    path = tmp_path / "cycle-soft/worker.json"
    row = json.loads(path.read_text())
    row["sent_at"] -= 3600
    path.write_text(json.dumps(row))
    cycle.Requests(tmp_path).request("worker", "a newer request")
    cli._cycle_plan(argparse.Namespace(root=tmp_path), Agent(name="worker"),
                    "", _Panes({}), None)
    assert not soft_cycle.pending(tmp_path, "worker")


# --- 3. the baseline: an idle agent's old row, and the reason printed ----------

def claude_transcripts(tmp_path, at):
    project = tmp_path / ".claude" / "projects" / "-w-worker"
    project.mkdir(parents=True)
    transcript = project / "old.jsonl"
    transcript.write_text("{}\n")
    os.utime(transcript, (at, at))
    return project, transcript


def test_old_row_is_current_when_its_claude_transcript_is_the_newest(tmp_path):
    at = time.time() - 4000
    _, transcript = claude_transcripts(tmp_path, at - 5)
    hook(tmp_path, transcript=transcript, at=at)
    assert soft_cycle.snapshot(tmp_path, "worker")["identity"]["session_id"] == "old"


def test_old_row_is_refused_when_a_newer_session_transcript_exists(tmp_path):
    at = time.time() - 4000
    project, transcript = claude_transcripts(tmp_path, at - 5)
    (project / "newer.jsonl").write_text("{}\n")  # a session the hooks never saw
    hook(tmp_path, transcript=transcript, at=at)
    with pytest.raises(ValueError, match="cannot prove"):
        soft_cycle.snapshot(tmp_path, "worker")


def test_old_row_is_refused_when_its_transcript_moved_on_without_the_hook(tmp_path):
    at = time.time() - 4000
    _, transcript = claude_transcripts(tmp_path, at - 5)
    os.utime(transcript, (at + 600, at + 600))
    hook(tmp_path, transcript=transcript, at=at)
    with pytest.raises(ValueError):
        soft_cycle.snapshot(tmp_path, "worker")


def test_baseline_failure_prints_its_reason(tmp_path, monkeypatch, capsys):
    runtime = soft_world(monkeypatch)
    hook(tmp_path, at=time.time() - 4000)  # not a Claude transcript path
    cycle.Requests(tmp_path).request("worker", "checkpoint")
    assert not cli._cycle_soft(argparse.Namespace(root=tmp_path),
        Agent(name="worker", dangerous=False), "worker", "p", Pane(), runtime)
    err = capsys.readouterr().err
    assert "ValueError: hook session identity is" in err and "cannot prove" in err


# --- 4/5. settling: a served cycle, a fresh process, an explicit cancel -------

def test_an_operator_cycle_that_performs_serves_the_pending_request(tmp_path, monkeypatch):
    cycle.Requests(tmp_path).request("worker", "checkpoint")
    monkeypatch.setattr(cli, "_cycle_stop_refusal", lambda *a: None)
    monkeypatch.setattr(cli, "_perform_cycle_locked", lambda *a: (cli.OK, cycle.RESPAWN))
    a = argparse.Namespace(root=tmp_path)  # not _automatic_cycle
    assert cli._perform_cycle(a, Agent(name="worker"), "worker", "p", None, None,
                              cycle.Plan(cycle.RESPAWN, "x"), None)[0] == cli.OK
    assert "worker" not in cycle.Requests(tmp_path).pending()


def test_CONTROL_a_failed_operator_cycle_keeps_the_request(tmp_path, monkeypatch):
    cycle.Requests(tmp_path).request("worker", "checkpoint")
    monkeypatch.setattr(cli, "_cycle_stop_refusal", lambda *a: None)
    monkeypatch.setattr(cli, "_perform_cycle_locked", lambda *a: (cli.CANNOT_TELL, cycle.SOFT))
    cli._perform_cycle(argparse.Namespace(root=tmp_path), Agent(name="worker"), "worker",
                       "p", None, None, cycle.Plan(cycle.SOFT, "x"), None)
    assert "worker" in cycle.Requests(tmp_path).pending()


@pytest.mark.parametrize("source,settled", [("startup", True), ("clear", False),
                                            ("compact", False), ("resume", False)])
def test_a_newly_started_process_settles_its_predecessors_request(tmp_path, source, settled):
    cycle.Requests(tmp_path).request("worker", "checkpoint")
    later = time.time() + 1
    assert session_anchor.settle_cycle_request(str(tmp_path), "worker",
                                               {"source": source}, now=later) is settled
    assert ("worker" not in cycle.Requests(tmp_path).pending()) is settled


def test_a_request_made_after_the_session_started_is_kept(tmp_path):
    cycle.Requests(tmp_path).request("worker", "checkpoint")
    assert not session_anchor.settle_cycle_request(
        str(tmp_path), "worker", {"source": "startup"}, now=time.time() - 60)
    assert "worker" in cycle.Requests(tmp_path).pending()


class Reg:
    def __init__(self, **roles):
        self.roles = roles

    def get(self, name):
        return Agent(name=name, role=self.roles[name])


def cancel(tmp_path, monkeypatch, who, caller, **roles):
    monkeypatch.setattr(cli, "_registry", lambda a: Reg(**roles))
    if caller is None:
        monkeypatch.delenv("SHANTY_AGENT", raising=False)
    else:
        monkeypatch.setenv("SHANTY_AGENT", caller)
    return cli._cancel_cycle_request(argparse.Namespace(
        root=tmp_path, agent=who, self_=False, dry_run=False))


@pytest.mark.parametrize("caller,role", [("worker", "worker"), ("hammond", "administrator"),
                                         ("sattler", "lead"), (None, None)])
def test_cancel_withdraws_request_and_marker_and_reads_back(tmp_path, monkeypatch, capsys,
                                                            caller, role):
    hook(tmp_path)
    cycle.Requests(tmp_path).request("worker", "checkpoint")
    soft_cycle.begin(tmp_path, "worker")
    roles = {"worker": "worker", **({caller: role} if caller else {})}
    assert cancel(tmp_path, monkeypatch, "worker", caller, **roles) == cli.OK
    assert "worker" not in cycle.Requests(tmp_path).pending()
    assert not soft_cycle.pending(tmp_path, "worker")
    assert "Read back: absent" in capsys.readouterr().out


def test_cancel_by_another_worker_is_refused_and_changes_nothing(tmp_path, monkeypatch):
    cycle.Requests(tmp_path).request("worker", "checkpoint")
    assert cancel(tmp_path, monkeypatch, "worker", "other",
                  worker="worker", other="worker") == cli.REFUSED
    assert "worker" in cycle.Requests(tmp_path).pending()


def test_cancel_with_nothing_pending_is_ok_and_says_so(tmp_path, monkeypatch, capsys):
    assert cancel(tmp_path, monkeypatch, "worker", "worker", worker="worker") == cli.OK
    assert "nothing withdrawn" in capsys.readouterr().out


def test_cancel_is_reachable_from_the_real_parser(tmp_path, monkeypatch, capsys):
    cycle.Requests(tmp_path).request("worker", "checkpoint")
    monkeypatch.delenv("SHANTY_AGENT", raising=False)
    assert cli.main(["--root", str(tmp_path), "agent", "cycle", "worker", "--cancel"]) == cli.OK
    assert "worker" not in cycle.Requests(tmp_path).pending()


# --- 6. tend's wording ----------------------------------------------------------

def notifier(tmp_path):
    panes = _Panes({"shanty-malcolm": ""})
    reg = _Reg([Agent(name="malcolm", role="worker", pane="shanty-malcolm")])
    return CycleBlockedNotifier(tmp_path, reg, panes), panes


def test_a_pathless_refusal_reports_its_reason_not_an_unreadable_tree(tmp_path):
    n, panes = notifier(tmp_path)
    n.sweep({"malcolm": {"refused": {"reason": "pane reads ?, not idle", "paths": []}}})
    (_, text), = panes.sent
    assert "unreadable tree" not in text
    assert "pane reads ?, not idle" in text and "--cancel" in text


def test_CONTROL_a_tree_refusal_still_names_the_tree(tmp_path):
    n, panes = notifier(tmp_path)
    n.sweep({"malcolm": {"refused": {"reason": "lost", "paths": ["/w/quipu-wt/malcolm"]}}})
    (_, text), = panes.sent
    assert "BLOCKED on /w/quipu-wt/malcolm" in text and "st repo push" in text


# --- 7. the context Stop hook: say it once, then let stops through -----------

def ctx_world(tmp_path):
    (tmp_path / "shantytown.toml").write_text(
        '[session_budget]\ncontext_window = 1000\ncontext_threshold_pct = 70\n')
    path = tmp_path / "session.jsonl"
    path.write_text(json.dumps({"message": {"model": "m", "usage": {
        "input_tokens": 2, "cache_read_input_tokens": 988,
        "cache_creation_input_tokens": 0}}}) + "\n")
    return Agent(name="reader", role="worker", pane="p"), {
        "session_id": "s1", "transcript_path": str(path)}


def blocks(tmp_path, card, payload, monkeypatch, capsys):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    if not stop_policy.stop_advice(tmp_path, card):
        capsys.readouterr()
        return None
    return json.loads(capsys.readouterr().out)["reason"]


@pytest.mark.parametrize("kind", ["unverified-clear", "pathless-refusal"])
def test_an_unmovable_request_is_said_once_then_stops_pass(tmp_path, monkeypatch, capsys, kind):
    card, payload = ctx_world(tmp_path)
    requests = cycle.Requests(tmp_path)
    requests.request(card.name, "checkpoint")
    if kind == "unverified-clear":
        hook(tmp_path, agent=card.name)
        soft_cycle.begin(tmp_path, card.name)
        # stale: past stop_policy's own silent window, so only this rule decides
        monkeypatch.setattr(cycle.Requests, "age", lambda *_: cycle.stuck_after() + 1)
    else:
        requests.mark_refused(card.name, "pane reads ?, not idle")
    first = blocks(tmp_path, card, payload, monkeypatch, capsys)
    assert first and "already pending" in first and "will not block again" in first
    for _ in range(3):
        assert blocks(tmp_path, card, payload, monkeypatch, capsys) is None


def test_CONTROL_without_a_request_the_hard_hint_keeps_blocking(tmp_path, monkeypatch, capsys):
    card, payload = ctx_world(tmp_path)
    for _ in range(2):
        assert "HARD HANDOFF" in blocks(tmp_path, card, payload, monkeypatch, capsys)


def test_CONTROL_a_new_request_speaks_once_more(tmp_path, monkeypatch, capsys):
    card, payload = ctx_world(tmp_path)
    requests = cycle.Requests(tmp_path)
    requests.request(card.name, "first")
    requests.mark_refused(card.name, "pane busy")
    assert blocks(tmp_path, card, payload, monkeypatch, capsys)
    assert blocks(tmp_path, card, payload, monkeypatch, capsys) is None
    time.sleep(0.01)
    requests.request(card.name, "second")
    requests.mark_refused(card.name, "pane busy")
    assert blocks(tmp_path, card, payload, monkeypatch, capsys)
