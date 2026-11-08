from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from shantytown.answer import Answer
from shantytown.backlog_hygiene import stale_review
from shantytown import ranking_check

NOW = datetime(2026, 11, 8, tzinfo=timezone.utc)


def work(ident="old", **values):
    return dict(id=ident, status="open", priority=3, labels=[], assignee=None,
                updated_at="2026-10-09T00:00:00Z") | values


def test_exact_boundary_and_stable_oldest_order_without_mutating_snapshot():
    rows = [work("boundary"), work("recent", updated_at="2026-10-09T00:00:01Z"),
            work("older", updated_at="2026-10-01T00:00:00-04:00")]
    before = deepcopy(rows)
    text = stale_review(rows, now=NOW)
    assert "2 unowned P3/P4" in text and "older, boundary" in text
    assert "0 freshness UNKNOWN" in text and "recent" not in text
    assert rows == before
    assert "supplied READY scope only" in text and "no automatic closure" in text
    assert "Inbox/deferred cull coverage not measured" in text


@pytest.mark.parametrize("values", [
    {"priority": 0}, {"priority": 1}, {"priority": 2}, {"assignee": "worker"},
    {"status": "in_progress"}, {"status": "deferred"}, {"status": "closed"},
    {"title": "ASK Stiwi preserve this"}, {"labels": ["desk"]},
    {"blocker_kind": "blocked:human"}, {"labels": ["deploy-operation"]},
    {"agent_context": '{"deploy_admission": {"phase": "planned"}}'},
    {"blocked_by": ["required"]}, {"labels": ["parked:by-design"]},
    {"title": "inbox: old pointer"}, {"labels": ["anchor"]},
])
def test_protected_and_out_of_scope_records_never_become_cull_candidates(values):
    assert stale_review([work(**values)], now=NOW) is None


@pytest.mark.parametrize("value", [None, "", "yesterday", "2026-10-01", 0,
                                  "2026-10-01T00:00:00", "2026-11-09T00:00:00Z"])
def test_missing_malformed_timezonefree_or_future_freshness_is_unknown(value):
    text = stale_review([work(updated_at=value)], now=NOW)
    assert "0 unowned P3/P4" in text and "1 freshness UNKNOWN" in text


def test_candidate_list_is_bounded_but_count_is_not_silently_capped():
    text = stale_review([work(f"id{i}") for i in range(7)], now=NOW)
    assert "7 unowned P3/P4" in text and "+2 more" in text
    assert "id5" not in text and "id6" not in text
    with pytest.raises(ValueError, match="coverage bound"):
        stale_review([work(str(i)) for i in range(5001)], now=NOW)
    with pytest.raises(ValueError, match="identity UNKNOWN"):
        stale_review([work(), work()], now=NOW)


def test_scheduled_sweep_reuses_snapshot_and_does_not_page_for_stale_work(tmp_path):
    rows = [work(updated_at="2020-01-01T00:00:00Z")]
    before = deepcopy(rows)
    calls, logs = [], []
    reg = SimpleNamespace(all=lambda: Answer.complete_read([], how="fixture"))
    panes = SimpleNamespace(exists=lambda p: True)

    def snapshot():
        calls.append("snapshot")
        return rows, rows

    def push(*args):
        raise AssertionError("stale proposal cannot create an administrator page")

    for _ in range(2):
        assert ranking_check.sweep(tmp_path, reg, panes, snapshot=snapshot,
                                   log=logs.append, counts_reader=lambda root: "counts",
                                   push=push) == []
    assert calls == ["snapshot", "snapshot"]
    assert rows == before
    assert len(logs) == 2 and "1 unowned P3/P4" in logs[1]


def test_unknown_hygiene_does_not_erase_existing_p0_advisory(tmp_path):
    rows = [work("urgent", priority=0), work("urgent", priority=0)]
    reg = SimpleNamespace(all=lambda: Answer.complete_read([], how="fixture"))
    text, key, actionable = ranking_check.report(
        tmp_path, rows, rows, reg, SimpleNamespace(exists=lambda p: True),
        counts_reader=lambda root: "counts")
    assert actionable and "stale-work review" not in text
    logs, sent = [], []
    ranking_check.sweep(tmp_path, reg, SimpleNamespace(exists=lambda p: True),
                       snapshot=lambda: (rows, rows), counts_reader=lambda root: "counts",
                       log=logs.append, push=lambda *args: sent.append(args) or True)
    assert any("stale-work review UNKNOWN" in line for line in logs)
    assert ranking_check.report(tmp_path, rows, rows, reg,
                               SimpleNamespace(exists=lambda p: True),
                               counts_reader=lambda root: "counts")[1] == key


def test_hygiene_changes_cannot_repeat_an_existing_p0_page(tmp_path):
    urgent = work("urgent", priority=0)
    stale = work(updated_at="2020-01-01T00:00:00Z")
    # Keep the existing ranking snapshot fixed. Only the READY P3 witness
    # changes; its own independent log may change, never the P0 notification.
    ready, rows = [urgent, stale], [urgent, stale]
    reg = SimpleNamespace(all=lambda: Answer.complete_read([], how="fixture"))
    panes = SimpleNamespace(exists=lambda p: True)
    sent, logs = [], []
    args = dict(snapshot=lambda: (ready, rows), counts_reader=lambda root: "counts",
                push=lambda *args: sent.append(args) or True, log=logs.append)
    ranking_check.sweep(tmp_path, reg, panes, **args)
    stale["updated_at"] = "2999-01-01T00:00:00Z"
    ranking_check.sweep(tmp_path, reg, panes, **args)
    assert len(sent) == 1
    assert all("stale-work review" not in str(call) for call in sent)
    ready.pop()
    ranking_check.sweep(tmp_path, reg, panes, **args)
    assert "no eligible records" in logs[-1]


def test_hygiene_ledger_permission_failure_cannot_suppress_p0_page(tmp_path, monkeypatch):
    from pathlib import Path
    real_exists = Path.exists

    def failed_ledger_stat(path):
        if path.name == "backlog_hygiene_log.json":
            raise PermissionError("fixture ledger unavailable")
        return real_exists(path)

    monkeypatch.setattr(Path, "exists", failed_ledger_stat)
    rows = [work("urgent", priority=0)]
    reg = SimpleNamespace(all=lambda: Answer.complete_read([], how="fixture"))
    sent, logs = [], []
    result = ranking_check.sweep(
        tmp_path, reg, SimpleNamespace(exists=lambda p: True),
        snapshot=lambda: (rows, rows), counts_reader=lambda root: "counts",
        push=lambda *args: sent.append(args) or True, log=logs.append)
    assert result == ["fleet"] and len(sent) == 1
    assert any("stale-work review UNKNOWN" in line for line in logs)
