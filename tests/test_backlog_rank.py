"""A query order is evidence, never permission to mutate another owner's work."""
from datetime import datetime, timezone

import pytest

from shantytown.backlog_rank import ordered

NOW = datetime(2026, 11, 8, 6, 30, tzinfo=timezone.utc)


def item(ident, **fields):
    return dict(id=ident, revision=2, priority=1, status="open", assignee=None, **fields)


def test_graph_order_changes_pickup_without_mutating_source_rows():
    old, due = item("old"), item("due")
    def reader(root, name, params, **bounds):
        assert name == "seeds_work_rank_v1"
        assert params["id00"] == "due" and params["id01"] == "old"
        assert bounds == dict(limit=65, timeout=8)
        return [dict(row, sampled_at=params["now"]) for row in (due, old)]
    assert ordered(None, [old, due], owner="ada", board="urn:board", reader=reader, now=NOW) == [due, old]
    assert old == item("old") and due == item("due")


@pytest.mark.parametrize("change", [
    lambda rows: rows[:1],
    lambda rows: [rows[0], rows[0]],
    lambda rows: [dict(rows[0], revision=3), rows[1]],
    lambda rows: [dict(rows[0], assignee="someone-else"), rows[1]],
    lambda rows: [dict(rows[0], priority=0), rows[1]],
    lambda rows: [dict(rows[0], status="deferred"), rows[1]],
    lambda rows: [dict(rows[0], sampled_at="2026-11-07T00:00:00Z"), rows[1]],
])
def test_incomplete_changed_or_stale_query_cannot_authorize_pickup(change):
    candidates = [item("a"), item("b")]
    def reader(root, name, params, **bounds):
        return change([dict(row, sampled_at=params["now"]) for row in candidates])
    with pytest.raises(ValueError):
        ordered(None, candidates, owner="ada", board="urn:board", reader=reader, now=NOW)


def test_query_refusal_has_no_fallback_or_write():
    calls = []
    def refused(*args, **kwargs):
        calls.append(1)
        raise PermissionError("refused")
    with pytest.raises(PermissionError):
        ordered(None, [item("a")], owner="ada", board="urn:board", reader=refused, now=NOW)
    assert calls == [1]


@pytest.mark.parametrize("outcome", [True, False, "unknown"])
def test_ready_p1_beats_owned_p2_only_after_verified_claim(outcome):
    from shantytown.backlog_rank import next_after_anchor
    low = dict(item("owned"), priority=2, assignee="ada")
    high = item("unowned")
    foreign = dict(item("foreign"), priority=0, assignee="other")
    rows = {r["id"]: r for r in (low, high, foreign)}
    claims = []
    def claim(row, owner):
        claims.append((row["id"], row["revision"], owner))
        if outcome == "unknown":
            raise RuntimeError("indeterminate")
        return outcome
    def reader(root, name, params, **bounds):
        assert "foreign" not in params.values()
        return [dict(row, sampled_at=params["now"]) for row in (high, low)]
    args = dict(owner="ada", board="urn:board", read_current=rows.__getitem__,
                claim=claim, admit=lambda rows: rows, reader=reader, now=NOW)
    if outcome == "unknown":
        with pytest.raises(RuntimeError, match="indeterminate"):
            next_after_anchor(None, list(rows.values()), [low], **args)
    else:
        selected, claimed = next_after_anchor(None, list(rows.values()), [low], **args)
        assert selected == (high if outcome else low)
        assert claimed is outcome
    assert claims == [("unowned", 2, "ada")]
    assert low["assignee"] == "ada" and low["status"] == "open"


def test_newly_held_candidate_never_reaches_query_or_claim():
    from shantytown.backlog_rank import next_after_anchor
    low = dict(item("owned"), priority=2, assignee="ada")
    high = item("unowned")
    def read(ident):
        return low if ident == "owned" else dict(high, defer_until="2026-11-09T00:00:00Z")
    def forbidden(*args, **kwargs):
        raise AssertionError("must stop before this side effect")
    with pytest.raises(ValueError, match="held"):
        next_after_anchor(None, [low, high], [low], owner="ada", board="urn:board",
                          read_current=read, claim=forbidden, admit=forbidden,
                          reader=forbidden, now=NOW)


@pytest.mark.parametrize("room, sdk_code", [(False, 0), (True, 4), (True, 8), (True, 0)])
def test_native_claim_retains_capacity_cas_and_verified_readback(monkeypatch, room, sdk_code):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from shantytown import plate_capacity, seeds_plate
    from shantytown.sd import SdTracker
    tracker = object.__new__(SdTracker)
    tracker.timeout = 1
    writes = []
    row = item("ready")
    def ensure_room(*args, **kwargs):
        if not room:
            raise plate_capacity.PlateFull("full")
    monkeypatch.setattr(plate_capacity, "assignment_lock", lambda *args: nullcontext())
    monkeypatch.setattr(plate_capacity, "ensure_room", ensure_room)
    monkeypatch.setattr(seeds_plate, "unblocked_ids", lambda *args, **kw: {"ready"})
    tracker.prove_store = lambda: SimpleNamespace(graph="urn:board")
    def update(*args):
        writes.append(args)
        return SimpleNamespace(returncode=sdk_code)
    tracker._bd_for = update
    tracker.stranded_read = lambda _: dict(row, revision=3, status="in_progress", assignee="ada")
    if not room:
        with pytest.raises(plate_capacity.PlateFull):
            tracker.claim_ranked_pickup(row, "ada")
        assert writes == []
    elif sdk_code == 8:
        with pytest.raises(RuntimeError, match="UNKNOWN"):
            tracker.claim_ranked_pickup(row, "ada")
    else:
        assert tracker.claim_ranked_pickup(row, "ada") is (sdk_code == 0)
    if writes:
        assert len(writes) == 1
        assert "--if-revision=2" in writes[0]
        assert "--assignee=ada" in writes[0]
