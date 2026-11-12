"""aegis-6vto.4: plates are served from Now, then Next by rank (Stiwi 2026-11-11).

P0-P4 stays severity. Later and unlaned items keep the previous order, so a
board without lanes plates exactly as before.
"""
import json
import subprocess

import pytest

from shantytown import br
from shantytown.protocols import plate_key
from shantytown.sd import SdTracker, StoreProof
from test_plate_readiness import FakeStore, row
from shantytown.beads import plate as beads_plate


def r(ident, priority, lane=None, rank=None, created="2026-11-01T00:00:00Z", status="open"):
    return dict(id=ident, title=ident, assignee="worker", status=status, priority=priority,
                lane=lane, rank=rank, created_at=created)


def order(rows, ready=None):
    ready = {x["id"] for x in rows} if ready is None else ready
    return [x["id"] for x in sorted(rows, key=lambda x: plate_key(
        x["status"], x["priority"], x["id"], ready, rank=x.get("rank"),
        created_at=x.get("created_at"), lane=x.get("lane")))]


def test_now_then_next_by_rank_then_previous_order():
    rows = [r("p0-unlaned", 0), r("p0-later", 0, "later"), r("p3-next-r2", 3, "next", "2"),
            r("p1-next-r1", 1, "next", "1"), r("p4-now", 4, "now"), r("p2-unlaned", 2)]
    assert order(rows) == ["p4-now", "p1-next-r1", "p3-next-r2",
                           "p0-later", "p0-unlaned", "p2-unlaned"]


def test_priority_does_not_order_inside_a_lane_but_rank_then_age_does():
    rows = [r("p0-new", 0, "now", created="2026-11-03T00:00:00Z"),
            r("p3-old", 3, "now", created="2026-11-01T00:00:00Z"),
            r("p4-ranked", 4, "now", "5", created="2026-11-05T00:00:00Z")]
    assert order(rows) == ["p4-ranked", "p3-old", "p0-new"]


def test_no_lanes_orders_exactly_as_the_previous_key():
    rows = [r("b", 1, rank="3"), r("a", 1), r("c", 0), r("d", None)]
    before = [x["id"] for x in sorted(rows, key=lambda x: plate_key(
        x["status"], x["priority"], x["id"], None, rank=x.get("rank"),
        created_at=x.get("created_at")))]
    assert order(rows) == before == ["c", "b", "a", "d"]


def test_in_hand_and_readiness_still_precede_lanes():
    rows = [r("now-blocked", 2, "now"), r("next-ready", 2, "next"),
            r("held-unlaned", 4, status="in_progress")]
    assert order(rows, ready={"next-ready"}) == ["held-unlaned", "next-ready", "now-blocked"]


@pytest.mark.parametrize("lane", ["NOW", "Now"])
def test_lane_case_is_normalised(lane):
    assert order([r("x", 0), r("y", 4, lane)]) == ["y", "x"]


def test_unknown_lane_value_keeps_previous_order():
    assert order([r("odd", 3, "someday"), r("p1", 1)]) == ["p1", "odd"]


def test_beads_backend_serves_now_first():
    items = [row("urgent", priority=0), row("chosen", priority=3)]
    items[1]["lane"] = "now"
    assert beads_plate(FakeStore(items, ready_ids=["urgent", "chosen"]), "ada").id == "chosen"


def test_seeds_cli_backend_serves_now_then_next_by_rank(monkeypatch):
    """The actual SdTracker plate (a BrTracker), from sd JSON rows carrying lane/rank."""
    monkeypatch.setattr(SdTracker, "prove_store", lambda self: StoreProof(
        "--quipu", None, "https://example.test", "test"))
    monkeypatch.setattr(SdTracker, "_use_remote_projection", lambda self: False, raising=False)
    rows = [r("p0-unlaned", 0, created="2026-10-01T00:00:00Z"),
            r("next-r2", 3, "next", "2"), r("next-r1", 4, "next", "1")]
    t = SdTracker(quipu="https://example.test", prefix="test")

    def run(*args):
        status = args[args.index("--status") + 1] if "--status" in args else None
        sel = [x for x in rows if status is None or x["status"] == status]
        return subprocess.CompletedProcess(args, 0, json.dumps(
            {"issues": sel, "total": len(sel), "has_more": False}), "")
    monkeypatch.setattr(t, "_bd", run)
    monkeypatch.setattr(br, "name_the_blocker", lambda _, item: item)
    assert br.plate(t, "worker").id == "next-r1"
    rows.append(r("now", 4, "now"))
    assert br.plate(t, "worker").id == "now"


def test_seeds_projection_reads_the_lane_predicate():
    from shantytown import seeds_plate
    assert seeds_plate.FIELDS[seeds_plate.SEEDS + "ontology/lane"] == "lane"
