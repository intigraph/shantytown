"""A stop reads its own active anchors without global SDK hydration."""
from types import SimpleNamespace

import pytest

from shantytown import feed_check, stop_event
from shantytown.answer import Answer, PartialAnswer


def test_native_active_uses_exact_owner_projection(monkeypatch, tmp_path):
    calls = []
    own = {"id": "own", "title": "work", "assignee": "project/crew/tim"}
    tracker = SimpleNamespace(haul_active_rows=lambda owner: (
        calls.append(owner) or Answer.complete_read([own], how="fixture")))
    monkeypatch.setattr(feed_check, "_br_tracker", lambda *a: tracker)
    monkeypatch.setattr(stop_event, "_bd_json", lambda *a, **k: pytest.fail("global read"))
    assert stop_event._haul_active("tim", None, tmp_path, None) == [own]
    assert calls == ["tim"]


@pytest.mark.parametrize("fault", ["partial", "raises"])
def test_unknown_active_never_falls_back(monkeypatch, tmp_path, fault):
    def projected(owner):
        if fault == "raises":
            raise RuntimeError("unproven")
        return Answer.capped([], how="fixture", caveat="truncated")
    monkeypatch.setattr(feed_check, "_br_tracker", lambda *a: SimpleNamespace(haul_active_rows=projected))
    monkeypatch.setattr(stop_event, "_bd_json", lambda *a, **k: pytest.fail("global read"))
    with pytest.raises((RuntimeError, PartialAnswer)):
        stop_event._haul_active("tim", None, tmp_path, None)


@pytest.mark.parametrize("tracker", [None, SimpleNamespace(),
                                    SimpleNamespace(haul_active_rows=lambda owner: None)])
def test_only_legacy_backends_keep_existing_read(monkeypatch, tmp_path, tracker):
    monkeypatch.setattr(feed_check, "_br_tracker", lambda *a: tracker)
    calls = []
    monkeypatch.setattr(stop_event, "_bd_json", lambda args, *a, **k: calls.append(args) or [])
    assert stop_event._haul_active("tim", None, tmp_path, None) == []
    assert calls == [["list", "--status", "in_progress", "--limit", "0"]]


def test_native_active_projection_observes_blocker_closure_each_pass(monkeypatch):
    from shantytown import seeds_plate
    from shantytown.sd import SdTracker
    from shantytown.answer import Answer
    rows = [{"id": "gated", "status": "in_progress"},
            {"id": "ready", "status": "in_progress"}]
    t = SdTracker(quipu="http://example.test", prefix="test")
    monkeypatch.setattr(t, "_use_remote_projection", lambda: True)
    monkeypatch.setattr(t, "prove_store", lambda: object())
    monkeypatch.setattr(t, "_tend_order", lambda values: values)
    monkeypatch.setattr(seeds_plate, "owner_rows", lambda *a, **k: Answer.complete_read(rows, how="fixture"))
    allowed = {"ready"}
    monkeypatch.setattr(seeds_plate, "unblocked_ids", lambda *a, **k: allowed)
    assert [r["id"] for r in t.haul_active_rows("worker").exact()] == ["ready"]
    allowed.add("gated")
    assert [r["id"] for r in t.haul_active_rows("worker").exact()] == ["gated", "ready"]
    def unknown(*a, **k):
        raise ValueError("dependency proof unavailable")
    monkeypatch.setattr(seeds_plate, "unblocked_ids", unknown)
    import pytest
    with pytest.raises(ValueError, match="dependency proof"):
        t.haul_active_rows("worker")
