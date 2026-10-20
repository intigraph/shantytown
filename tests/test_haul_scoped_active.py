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
