"""aegis-qbl: ceiling-held work moves to a claude agent with headroom."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from shantytown import ceiling_transfer as ct
from shantytown import cli, tend
from shantytown import session_budget as sb
from shantytown.dispatch import DispatchedButUntracked
from shantytown.protocols import Agent, WorkItem


def held(agent="kelly", item="aegis-z2k", why="session ceiling"):
    return ct.Holder(agent, item, why, "4 haul items this session — the ceiling is 4")


def cand(agent, harness="claude", assigned=0, unavailable=""):
    return ct.Candidate(agent, harness, assigned, unavailable)


# ---- planner ---------------------------------------------------------------

def test_moves_to_the_claude_agent_with_most_room():
    p = ct.plan([held()], [cand("ellie", assigned=4), cand("ian", assigned=1)])
    assert [(m.item, m.frm, m.to) for m in p.moves] == [("aegis-z2k", "kelly", "ian")]
    assert p.stays == []


def test_never_moves_to_a_non_claude_or_unavailable_or_full_agent():
    p = ct.plan([held()], [cand("wu", harness="codex"),
                           cand("ian", unavailable="at its own ceiling"),
                           cand("ellie", assigned=ct.PLATE_CAP)])
    assert p.moves == []
    assert p.stays[0].item == "aegis-z2k" and "headroom" in p.stays[0].why


def test_a_holder_is_never_its_own_target_and_room_is_consumed():
    holders = [held("harding", "a-1"), held("kelly", "a-2"), held("ian", "a-3")]
    p = ct.plan(holders, [cand("harding"), cand("ellie", assigned=ct.PLATE_CAP - 1)])
    assert [(m.item, m.to) for m in p.moves] == [("a-1", "ellie")]
    assert {s.item for s in p.stays} == {"a-2", "a-3"}


def test_note_and_comment_name_source_reason_and_evidence():
    m = ct.plan([held()], [cand("ellie")]).moves[0]
    for text in (m.note(), m.comment()):
        assert "kelly" in text and "session ceiling" in text and "the ceiling is 4" in text
    assert "ellie" in m.comment()


# ---- apply -----------------------------------------------------------------

def test_apply_dispatches_once_then_comments_and_emits():
    calls, comments, events, log = [], [], [], []
    m = ct.Move("x-1", "kelly", "ellie", "usage limit", "banner")
    out = ct.apply([m], dispatch=lambda *c: calls.append(c),
                   comment=lambda i, b: comments.append((i, b)),
                   emit=events.append, log=log.append)
    assert calls == [("x-1", "ellie", m.note())]
    assert comments == [("x-1", m.comment())]
    assert events[0]["kind"] == "ceiling-transfer" and events[0]["to"] == "ellie"
    assert out[0].moved and out[0].commented


def test_a_refused_dispatch_writes_nothing_and_is_not_retried():
    calls, comments, events, log = [], [], [], []

    def busy(*c):
        calls.append(c)
        raise RuntimeError("target pane is busy")

    out = ct.apply([ct.Move("x-1", "kelly", "ellie", "usage limit", "banner")],
                   dispatch=busy, comment=lambda *c: comments.append(c),
                   emit=events.append, log=log.append)
    assert len(calls) == 1 and comments == [] and events == []
    assert not out[0].moved and "busy" in out[0].detail
    assert "stays with kelly" in log[0]


def test_a_comment_failure_after_a_move_is_loud_and_keeps_the_move():
    log = []

    def bad_comment(*c):
        raise OSError("store down")

    out = ct.apply([ct.Move("x-1", "kelly", "ellie", "usage limit", "banner")],
                   dispatch=lambda *c: None, comment=bad_comment,
                   emit=lambda e: None, log=log.append)
    assert out[0].moved and not out[0].commented
    assert any("MOVED" in line and "not recorded" in line for line in log)


# ---- the tend sweep, every seam injected -----------------------------------

LIMITS = sb.Limits(max_items=4)


def _known(name, ceilinged):
    if name in ceilinged:
        spent = sb.Spend(session=name, items=4)
        return LIMITS, spent, sb.Ceiling("items", 4, 4, spent)
    return LIMITS, sb.Spend(session=name, items=0), None


def _sweep(tmp_path, *, ceilinged=("kelly",), findings=None, gaming=False,
           dry_run=False, counts=None, dispatch_raises=None, agents=None,
           budget=None):
    agents = agents or [Agent(name="kelly", harness="codex"),
                        Agent(name="ellie", harness="claude"),
                        Agent(name="wu", harness="codex")]
    findings = findings if findings is not None else [
        tend.Finding("kelly", "up", "ok"), tend.Finding("ellie", "up", "ok"),
        tend.Finding("wu", "up", "ok")]
    sent, comments = [], []

    class Disp:
        tracker = object()

        def go(self, item, to, *, note, reassign):
            sent.append((item, to, reassign))
            if dispatch_raises:
                raise dispatch_raises

    a = SimpleNamespace(root=tmp_path, dry_run=dry_run)
    log = []
    orig = cli.__dict__.get("_ceiling_transfer_sweep")
    import shantytown.work_item as wi
    saved = (wi._comments, wi._comment_body)
    store = {}

    def fake_comments(trk, item_id, body=None):
        if body is not None:
            store.setdefault(item_id, []).append({"body": body})
            comments.append((item_id, body))
        return store.get(item_id, [])

    wi._comments = fake_comments
    try:
        out = orig(a, agents, SimpleNamespace(findings=findings),
                   dispatcher=Disp(),
                   plate=lambda name: WorkItem(id=f"item-{name}", status="in_progress",
                                               assignee=name),
                   owner_count=lambda name: (counts or {}).get(name, 0),
                   budget=budget or (lambda name: _known(name, ceilinged)),
                   gaming=SimpleNamespace(held=gaming), log=log.append)
    finally:
        wi._comments, wi._comment_body = saved
    return out, sent, comments, log


def test_sweep_moves_a_ceilinged_codex_agents_item_to_live_claude(tmp_path):
    out, sent, comments, log = _sweep(tmp_path)
    assert sent == [("item-kelly", "ellie", True)]
    assert comments and comments[0][0] == "item-kelly"
    assert "from kelly to ellie" in comments[0][1]
    ledger = (tmp_path / "ceiling-transfers.jsonl").read_text()
    assert '"item": "item-kelly"' in ledger


def test_must_fail_control_no_ceiling_no_move(tmp_path):
    out, sent, comments, log = _sweep(tmp_path, ceilinged=())
    assert out == [] and sent == [] and comments == []


def test_usage_limited_without_fallback_is_a_source_but_failed_over_is_not(tmp_path):
    f = [tend.Finding("kelly", "up", tend.LIMITED, acted=False),
         tend.Finding("ellie", "up", "ok"), tend.Finding("wu", "up", "ok")]
    _, sent, _, _ = _sweep(tmp_path, ceilinged=(), findings=f)
    assert sent == [("item-kelly", "ellie", True)]
    f[0] = tend.Finding("kelly", "up", tend.LIMITED, acted=True)
    _, sent, _, _ = _sweep(tmp_path, ceilinged=(), findings=f)
    assert sent == []


@pytest.mark.parametrize("case", ["gaming", "target-full", "target-ceilinged",
                                  "target-down", "target-count-unknown"])
def test_sweep_refusals_move_nothing(tmp_path, case):
    kw = {}
    if case == "gaming":
        kw["gaming"] = True
    elif case == "target-full":
        kw["counts"] = {"ellie": ct.PLATE_CAP}
    elif case == "target-ceilinged":
        kw["ceilinged"] = ("kelly", "ellie")
    elif case == "target-down":
        kw["findings"] = [tend.Finding("kelly", "up", "ok"),
                          tend.Finding("ellie", "down", "down"),
                          tend.Finding("wu", "up", "ok")]
    _, sent, comments, _ = (_sweep(tmp_path, **kw) if case != "target-count-unknown"
                            else _sweep_unknown(tmp_path))
    assert sent == [] and comments == []


def _sweep_unknown(tmp_path):
    a = SimpleNamespace(root=tmp_path, dry_run=False)
    sent = []

    class Disp:
        tracker = object()

        def go(self, item, to, *, note, reassign):
            sent.append((item, to))

    cli._ceiling_transfer_sweep(
        a, [Agent(name="kelly", harness="codex"), Agent(name="ellie", harness="claude")],
        SimpleNamespace(findings=[tend.Finding("kelly", "up", "ok"),
                                  tend.Finding("ellie", "up", "ok")]),
        dispatcher=Disp(),
        plate=lambda n: WorkItem(id="item-kelly", status="in_progress", assignee=n),
        owner_count=lambda n: None,
        budget=lambda n: _known(n, ("kelly",)),
        gaming=SimpleNamespace(held=False), log=lambda m: None)
    return None, sent, [], None


def test_busy_target_refusal_is_reported_and_writes_nothing(tmp_path):
    out, sent, comments, log = _sweep(
        tmp_path, dispatch_raises=RuntimeError("TriageRefused: pane busy"))
    assert sent == [("item-kelly", "ellie", True)]
    assert comments == [] and not (tmp_path / "ceiling-transfers.jsonl").exists()
    assert any("stays with kelly" in line for line in log)


def test_dry_run_dispatches_nothing(tmp_path):
    out, sent, comments, log = _sweep(tmp_path, dry_run=True)
    assert sent == [] and comments == []
    assert any("would move item-kelly kelly -> ellie" in line for line in log)


# ---- receiver budget must be POSITIVELY known (wu review of ST248) ----------

@pytest.mark.parametrize("state,moves", [
    ("known-headroom", True),
    ("inactive-policy", True),
    ("exhausted", False),
    ("signal-lost", False),
    ("no-session", False),
    ("corrupt-read", False),
])
def test_receiver_budget_states(tmp_path, state, moves):
    def budget(name):
        if name != "ellie":
            return _known(name, ("kelly",))
        return {
            "known-headroom": (LIMITS, sb.Spend(session="ellie", items=1), None),
            "inactive-policy": (sb.Limits(), sb.Spend(), None),
            "exhausted": _known("ellie", ("ellie",)),
            "signal-lost": (LIMITS, sb.Spend(session="", signal_lost=True), None),
            "no-session": (LIMITS, sb.Spend(session=""), None),
            # gate()'s own exception path: INACTIVE limits with signal_lost.
            "corrupt-read": (sb.Limits(), sb.Spend(signal_lost=True), None),
        }[state]
    _, sent, _, _ = _sweep(tmp_path, budget=budget)
    assert sent == ([("item-kelly", "ellie", True)] if moves else [])


def test_receiver_budget_pure_order():
    assert ct.receiver_budget(sb.Limits(), sb.Spend(signal_lost=True), None)
    assert ct.receiver_budget(sb.Limits(), sb.Spend(), None) == ""


def test_delivered_but_untracked_is_not_reported_as_staying():
    log = []
    exc = DispatchedButUntracked("x-1", "ellie", "%9", OSError("store"))

    def raise_(*c):
        raise exc

    out = ct.apply([ct.Move("x-1", "kelly", "ellie", "usage limit", "banner")],
                   dispatch=raise_, comment=lambda *c: None,
                   emit=lambda e: None, log=log.append)
    assert not out[0].moved
    assert "DELIVERED to ellie" in log[0] and "verify ownership before retrying" in log[0]
    assert "stays with" not in log[0]


def test_busy_receiver_is_attempted_once_per_pass_without_stopping_other_receivers():
    from shantytown.dispatch import TriageRefused
    from shantytown.triage import Action, Decision

    moves = [ct.Move(f"item-{i}", "holder", "busy", "session ceiling", "fixture")
             for i in range(5)]
    moves.insert(2, ct.Move("control", "holder", "ready", "session ceiling", "fixture"))
    calls, comments, events, logs = [], [], [], []

    def dispatch(item, to, note):
        calls.append((item, to))
        if to == "busy":
            raise TriageRefused(Decision(Action.REFUSE, "pane is busy", {"busy": True}))

    out = ct.apply(moves, dispatch=dispatch, comment=lambda *c: comments.append(c),
                   emit=events.append, log=logs.append)
    assert calls == [("item-0", "busy"), ("control", "ready")]
    assert [o.move for o in out] == moves  # even skipped work has an outcome
    assert [o.move.item for o in out if o.moved] == ["control"]
    assert [c[0] for c in comments] == ["control"]
    assert [e["item"] for e in events] == ["control"]
    assert all("TriageRefused" in o.detail for o in out if not o.moved)
    assert sum("skipped" in line for line in logs) == 4

    # A refusal is an observation for this pass, never a persistent agent hold.
    later = []
    out = ct.apply([moves[0]], dispatch=lambda *c: later.append(c),
                   comment=lambda *c: None, emit=lambda e: None, log=lambda line: None)
    assert len(later) == 1 and out[0].moved


def test_item_level_failure_does_not_withhold_other_work_from_the_receiver():
    calls = []
    moves = [ct.Move("bad", "holder", "ready", "session ceiling", "fixture"),
             ct.Move("good", "holder", "ready", "session ceiling", "fixture")]

    def dispatch(item, to, note):
        calls.append(item)
        if item == "bad":
            raise ValueError("item is not dispatchable")

    out = ct.apply(moves, dispatch=dispatch, comment=lambda *c: None,
                   emit=lambda e: None, log=lambda line: None)
    assert calls == ["bad", "good"]
    assert not out[0].moved and out[1].moved


# ---- policy50 observations at the real sweep boundary ----------------------

def _advisory(tmp_path):
    import json
    return [json.loads(line) for line in
            (tmp_path / "ceiling-transfer-advisory.jsonl").read_text().splitlines()
            if json.loads(line)["phase"] != "start"]


def test_advisory_records_the_inputs_used_and_confirmed_dispatch(tmp_path):
    out, sent, _, _ = _sweep(tmp_path, counts={"ellie": 9})
    before, after = _advisory(tmp_path)
    assert sent == [("item-kelly", "ellie", True)] and out[0].moved
    assert before["sweep"] == after["sweep"]
    assert (before["phase"], after["phase"]) == ("plan", "outcomes")
    assert before["effect"] == "record" and before["adjudication"] == "ungraded"
    assert before["policy_version"] == "4e83e01ae8985b24"
    assert all(len(digest) == 64 for digest in before["code"].values())
    inputs = before["inputs"]
    assert inputs["counts"]["ellie"] == 9
    assert inputs["budgets"]["kelly"][2]["measure"] == "items"
    assert inputs["holders"][0]["why"] == "session ceiling"
    assert inputs["plan"]["moves"][0]["to"] == "ellie"
    assert after["inputs"]["outcomes"][0]["disposition"] == "confirmed"


def test_advisory_unknown_count_is_not_zero_or_a_move(tmp_path):
    _sweep_unknown(tmp_path)
    before, after = _advisory(tmp_path)
    assert before["inputs"]["counts"]["ellie"] is None
    candidate = next(c for c in before["inputs"]["candidates"] if c["agent"] == "ellie")
    assert candidate["unavailable"] == "plate count unknown"
    assert not before["inputs"]["plan"]["moves"]
    assert before["inputs"]["plan"]["stays"]
    assert after["inputs"]["outcomes"] == []


@pytest.mark.parametrize("lost,expected", [(True, False), (False, True)])
def test_advisory_distinguishes_inactive_policy_from_lost_signal(tmp_path, lost, expected):
    def budget(name):
        if name == "ellie":
            return sb.Limits(), sb.Spend(signal_lost=lost), None
        return _known(name, ("kelly",))
    _, sent, _, _ = _sweep(tmp_path, budget=budget)
    row = _advisory(tmp_path)[0]
    assert bool(sent) == expected
    assert row["inputs"]["budgets"]["ellie"][1]["signal_lost"] is lost
    # An unread count stays absent, not a fabricated complete zero.
    assert ("ellie" in row["inputs"]["counts"]) == expected


def test_advisory_delivered_untracked_retains_delivery_uncertainty(tmp_path):
    err = DispatchedButUntracked("item-kelly", "ellie", "%9", OSError("store"))
    _, sent, comments, _ = _sweep(tmp_path, dispatch_raises=err)
    row = _advisory(tmp_path)[-1]["inputs"]["outcomes"][0]
    assert len(sent) == 1 and not comments
    assert row["disposition"] == "delivered_untracked" and not row["moved"]
    assert "DispatchedButUntracked" in row["detail"]


@pytest.mark.parametrize("mode", ["gaming", "no_holders", "dry_run"])
def test_advisory_reports_scope_without_inventing_a_dispatch(tmp_path, mode):
    options = {"gaming": {"gaming": True},
               "no_holders": {"ceilinged": ()},
               "dry_run": {"dry_run": True}}[mode]
    _, sent, comments, _ = _sweep(tmp_path, **options)
    rows = _advisory(tmp_path)
    assert not sent and not comments and len(rows) == 1
    assert rows[0]["phase"] == {"gaming": "held", "no_holders": "no_holders",
                                "dry_run": "plan"}[mode]
    assert rows[0]["adjudication"] == "ungraded"


def test_advisory_write_failure_does_not_change_dispatch(tmp_path, monkeypatch):
    from shantytown import ceiling_advisory

    def denied(*args, **kwargs):
        raise PermissionError("fixture")

    monkeypatch.setattr(ceiling_advisory.os, "open", denied)
    out, sent, comments, log = _sweep(tmp_path)
    assert sent == [("item-kelly", "ellie", True)] and comments and out[0].moved
    assert sum("advisory capture UNKNOWN" in line for line in log) == 3
    assert not (tmp_path / "ceiling-transfer-advisory.jsonl").exists()


def test_advisory_types_refusal_and_skipped_without_a_second_send(tmp_path):
    from shantytown.dispatch import TriageRefused
    from shantytown.triage import Action, Decision
    calls = []

    def refuse(*args):
        calls.append(args)
        raise TriageRefused(Decision(Action.REFUSE, "busy", {}))

    moves = [ct.Move(str(i), "holder", "receiver", "session ceiling", "fixture")
             for i in range(2)]
    rows = ct.apply(moves, dispatch=refuse, comment=lambda *a: None,
                    emit=lambda *a: None, log=lambda *a: None)
    assert len(calls) == 1
    assert [r.disposition for r in rows] == ["refused", "not_attempted"]


def test_advisory_started_read_failure_is_unknown_not_an_empty_population(tmp_path):
    import json
    def broken(name):
        raise RuntimeError("fixture read failed")
    with pytest.raises(RuntimeError, match="fixture read failed"):
        _sweep(tmp_path, budget=broken)
    rows = [json.loads(line) for line in
            (tmp_path / "ceiling-transfer-advisory.jsonl").read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["phase"] == "start"
    assert rows[0]["inputs"]["inputs_observed"] is False
    assert rows[0]["adjudication"] == "ungraded"
