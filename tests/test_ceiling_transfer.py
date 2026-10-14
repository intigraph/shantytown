"""aegis-qbl: ceiling-held work moves to a claude agent with headroom."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from shantytown import ceiling_transfer as ct
from shantytown import cli, tend
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

class _Ceiling:
    def label(self):
        return "4 haul items this session — the ceiling is 4"


def _sweep(tmp_path, *, ceilinged=("kelly",), findings=None, gaming=False,
           dry_run=False, counts=None, dispatch_raises=None, agents=None):
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
                   ceiling=lambda name: _Ceiling() if name in ceilinged else None,
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
        ceiling=lambda n: _Ceiling() if n == "kelly" else None,
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
