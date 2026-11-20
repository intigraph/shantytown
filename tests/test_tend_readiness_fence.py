"""aegis-jve: candidate-scan readiness shares one watermark; claim proofs stay exact."""
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from shantytown import plate_capacity, seeds_plate, seeds_read_cache
from shantytown.sd import SdTracker

from test_seeds_read_cache import read, service  # noqa: F401  (fixture)

PROOF = SimpleNamespace(graph="urn:board", quipu_url="http://127.0.0.1:9")


def _tier():
    return seeds_read_cache._STALE_TTL.get()


def test_exact_reads_refuses_the_stale_tier_inside_stale_ok(service):  # noqa: F811
    proof, state = service
    with seeds_read_cache.stale_ok():
        assert _tier() > 0
        with seeds_read_cache.exact_reads():
            assert _tier() == 0
            assert seeds_read_cache._stale_fence_age() == 0
            assert seeds_read_cache.stale_lookup([proof.quipu_url, "Q"], lambda v: v) == (None, None)
            read(proof)
        assert _tier() > 0
    assert state["watermarks"] == 2  # the full exact before/after fence


def test_multi_batch_candidate_scan_pays_one_watermark_not_one_fence_per_batch(service):  # noqa: F811
    proof, state = service
    for batch in range(3):
        read(proof, f"SELECT exact-batch-{batch}")
    exact = state["watermarks"]
    assert exact >= 3  # at least one fence per batch on the exact path
    state["watermarks"] = 0
    seeds_read_cache.invalidate_stale()  # no reusable mark: the scan must observe once
    with seeds_read_cache.stale_ok():
        for batch in range(3):
            assert read(proof, f"SELECT scan-batch-{batch}")["rows"][0]["query"] == f"SELECT scan-batch-{batch}"
    assert state["watermarks"] == 1
    assert state["queries"] == 6  # every batch is still a live query


def _tracker(monkeypatch, seen):
    tracker = object.__new__(SdTracker)
    tracker.timeout = 1
    tracker.prove_store = lambda: PROOF
    tracker._use_remote_projection = lambda: True
    tracker._plate_projection_candidates = {}

    def unblocked(proof, rows, *, timeout=30):
        seen.append(_tier())
        return {row["id"] for row in rows}
    monkeypatch.setattr(seeds_plate, "unblocked_ids", unblocked)
    return tracker


def _row(identifier, status="open", **extra):
    return dict(id=identifier, title=identifier, status=status, priority=2,
                created_at="2026-11-20T00:00:00Z", assignee="ada", **extra)


def test_candidate_scans_read_readiness_in_the_stale_tier(monkeypatch):
    seen = []
    tracker = _tracker(monkeypatch, seen)
    rows = [_row("a"), _row("b", "in_progress")]
    answer = SimpleNamespace(exact=lambda: rows, complete=True, how="fixture")
    monkeypatch.setattr(seeds_plate, "owner_rows", lambda *a, **k: answer)
    monkeypatch.setattr(seeds_plate, "ranking_rows", lambda *a, **k: answer)
    tracker._tend_order = lambda rows: rows
    tracker.feed_rows(["ada"])
    tracker.haul_active_rows("ada")
    tracker.priority_rows()
    tracker.ranking_rows()
    tracker.prepare_roster(["ada"])
    assert len(seen) == 5
    assert all(tier > 0 for tier in seen)
    assert _tier() == 0  # the scope does not leak to the caller


def test_candidate_scan_obeys_the_stale_rollback(monkeypatch):
    monkeypatch.setenv("ST_SEEDS_STALE_TTL", "0")
    seen = []
    tracker = _tracker(monkeypatch, seen)
    tracker._candidate_ready([_row("a")])
    assert seen == [0]


def test_claim_readiness_proof_is_exact_even_inside_stale_ok(monkeypatch):
    seen = []
    tracker = _tracker(monkeypatch, seen)
    monkeypatch.setattr(plate_capacity, "assignment_lock", lambda *args: nullcontext())
    monkeypatch.setattr(plate_capacity, "ensure_room", lambda *args, **kwargs: None)
    row = dict(_row("ready"), assignee=None, revision=2)
    tracker._bd_for = lambda *args: SimpleNamespace(returncode=4)
    with seeds_read_cache.stale_ok():
        assert tracker.claim_ranked_pickup(row, "ada") is False
    assert seen == [0]
