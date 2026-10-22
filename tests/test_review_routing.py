"""Routing observations must refuse unknown availability and excess reads."""
import json
from types import SimpleNamespace
import urllib.error
import urllib.request

import pytest

from shantytown.review_routing import ReadBudgetExceeded, observe, read_budget, check_assignments


@pytest.mark.parametrize("harness,state,work,posture,expected", [
    ("codex", "up", "idle", "BYPASS", True),
    (None, "up", "idle", "BYPASS", False),
    ("claude", "up", "idle", "BYPASS", False),
    ("codex", "down", "idle", "BYPASS", False),
    ("codex", "up", "busy", "BYPASS", False),
    ("codex", "up", "ceiling", "BYPASS", False),
    ("codex", "up", "idle", "MANUAL", False),
])
def test_availability_requires_every_live_control(harness, state, work, posture, expected):
    card = SimpleNamespace(name="reviewer")
    rows = observe([card], [(card, state, work, posture)], lambda _: harness)
    assert rows[0]["available"] is expected


def request(query="SELECT ?s WHERE { ?s ?p ?o }", path="/query"):
    return urllib.request.Request("http://example.test" + path,
                                  data=json.dumps({"query": query}).encode())


def test_budget_counts_transport_and_refuses_before_seventh_send(monkeypatch):
    sent = []
    original = lambda req, **kw: sent.append(req)
    monkeypatch.setattr(urllib.request, "urlopen", original)
    with read_budget() as usage:
        for _ in range(6):
            urllib.request.urlopen(request())
        with pytest.raises(ReadBudgetExceeded):
            urllib.request.urlopen(request())
    assert len(sent) == usage["reads"] == 6
    assert urllib.request.urlopen is original


@pytest.mark.parametrize("req", [request("INSERT DATA {}"), request(path="/episode"),
                                   "http://example.test/query"])
def test_unknown_or_write_transport_never_sends(monkeypatch, req):
    def forbidden(*args, **kwargs):
        pytest.fail("unsafe request reached transport")
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    with read_budget() as usage, pytest.raises(ReadBudgetExceeded):
        urllib.request.urlopen(req)
    assert usage["reads"] == 0


def test_timeout_is_counted_and_opener_restored(monkeypatch):
    def timeout(req):
        raise urllib.error.HTTPError(req.full_url, 408, "timeout", {}, None)
    monkeypatch.setattr(urllib.request, "urlopen", timeout)
    with read_budget() as usage, pytest.raises(urllib.error.HTTPError):
        urllib.request.urlopen(request("PREFIX ex: <http://example.test/> SELECT ?s WHERE {}"))
    assert usage == {"reads": 1, "timeouts": 1}
    assert urllib.request.urlopen is timeout


def test_owner_projection_uses_the_same_transport_budget(monkeypatch):
    from shantytown import seeds_plate
    sent = []
    monkeypatch.setattr(urllib.request, "urlopen", lambda req: sent.append(req))
    before = seeds_plate.urlopen
    with read_budget(limit=1) as usage:
        seeds_plate.urlopen(request())
        with pytest.raises(ReadBudgetExceeded):
            seeds_plate.urlopen(request())
    assert len(sent) == usage["reads"] == 1
    assert seeds_plate.urlopen is before


def test_idle_pane_with_active_assignment_is_not_available():
    rows = [{"name": n, "available": True} for n in ("a", "b", "c")]
    def projection(owners):
        assert owners == ("a", "b", "c")
        return [{"assignee": "a", "status": "in_progress"},
                {"assignee": "b", "status": "hooked"}]
    check_assignments(rows, projection, turn=0)
    assert [row["name"] for row in rows if row["available"]] == ["c"]
    assert all(row["assignment_checked"] for row in rows)


def test_candidate_bound_rotates_and_unchecked_owners_are_unavailable():
    def run(turn):
        rows = [{"name": f"r{i:02}", "available": True} for i in range(20)]
        observed = []
        check_assignments(rows, lambda owners: observed.extend(owners) or [], turn=turn)
        assert len(observed) == 8
        assert sum(row["available"] for row in rows) == 8
        assert all(not row["available"] for row in rows if not row["assignment_checked"])
        return set(observed)
    assert run(0).isdisjoint(run(1))


def test_foreign_owner_refuses_projection():
    rows = [{"name": "a", "available": True}]
    with pytest.raises(ValueError, match="foreign owner"):
        check_assignments(rows, lambda _: [{"assignee": "other", "status": "in_progress"}], turn=0)
    assert not rows[0]["available"]
