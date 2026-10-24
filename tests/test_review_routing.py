"""Routing observations must refuse unknown availability and excess reads."""
import json
from types import SimpleNamespace
import urllib.error
import urllib.request

import pytest

from shantytown.review_routing import ReadBudgetExceeded, observe, read_budget, check_assignments
from shantytown.launchable import BYPASS, MANUAL


@pytest.mark.parametrize("harness,state,work,posture,expected", [
    ("codex", "up", "idle", BYPASS, True),
    (None, "up", "idle", BYPASS, False),
    ("claude", "up", "idle", BYPASS, False),
    ("codex", "down", "idle", BYPASS, False),
    ("codex", "up", "busy", BYPASS, False),
    ("codex", "up", "ceiling", BYPASS, False),
    ("codex", "up", "idle", MANUAL, False),
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


@pytest.mark.parametrize("mode,expected", [
    ("idle", True), ("manual", False), ("busy", False),
    ("unknown-harness", False), ("ceiling", False), ("assigned", False),
])
def test_real_crew_states_reaches_bounded_assignment_proof(
        tmp_path, monkeypatch, capsys, mode, expected):
    """Regression from the independent review: exercise the real verdict path."""
    import sys
    from shantytown import cli, deployment, session_budget, untracked, seeds_plate
    from shantytown import review_routing
    from shantytown.answer import Answer
    from shantytown.files import FilesRegistry
    from shantytown.sd import SdTracker

    crew = tmp_path / "crew"
    crew.mkdir()
    for name, retired in (("active", False), ("retired", True)):
        (crew / (name + ".json")).write_text(json.dumps(dict(
            role="worker", pane=name, harness="codex", retired=retired)))

    class Panes:
        def exists(self, pane):
            return True

        def capture(self, pane, **kwargs):
            busy = "• Working (2s • esc to interrupt)\n" if mode == "busy" else ""
            footer = ("? for shortcuts" if mode == "manual" else
                      "⏵⏵ bypass permissions on (shift+tab to cycle) · ← for agents")
            return busy + "❯ \n  " + footer

        def cmdline(self, pane):
            if mode == "unknown-harness":
                return "python fixture.py"
            command = "CODEX_HOME=/private-fixture/codex codex"
            return command if mode == "manual" else command + " --dangerously-bypass-approvals-and-sandbox"

    class PrivateTracker(SdTracker):
        @property
        def _bin(self):
            return sys.executable

        def prove_store(self):
            return SimpleNamespace(quipu_url="http://example.test", graph="https://example.test/board")

    tracker = PrivateTracker.__new__(PrivateTracker)
    projection_calls = []

    def owner_rows(*args, plate_owners, **kwargs):
        projection_calls.append(plate_owners)
        rows = ([dict(assignee="active", status="in_progress")]
                if mode == "assigned" else [])
        return Answer.complete_read(rows, how="private exact owner projection")

    for name, value in (
        ("_registry", lambda _: FilesRegistry(crew)),
        ("_panes", lambda _: Panes()),
        ("_runtime", lambda *_: SimpleNamespace(shows_ready_ui=lambda _: True)),
        ("_tracker", lambda _: tracker),
        ("shell_foreground", lambda *_: False),
        ("asks_a_question", lambda *_: False),
        ("auth_expired", lambda *_: False),
        ("limit_reached", lambda *_: False),
    ):
        monkeypatch.setattr(cli, name, value)
    monkeypatch.setattr(deployment, "local_host", lambda _: None)
    monkeypatch.setattr(session_budget, "at_ceiling", lambda *_:
                        SimpleNamespace(measure="items") if mode == "ceiling" else None)
    monkeypatch.setattr(untracked, "ledger_activity", lambda *_: (untracked.ACTIVITY_CLEAR, ""))
    monkeypatch.setattr(seeds_plate, "owner_rows", owner_rows)

    assert review_routing.command(SimpleNamespace(local=True, json=True, root=tmp_path)) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["complete"] is True
    rows = {row["name"]: row for row in result["agents"]}
    assert rows["active"]["available"] is expected
    assert rows["retired"]["available"] is False
    if mode in ("idle", "assigned"):
        assert rows["active"]["assignment_checked"] is True
        assert projection_calls == [("active",)]
    else:
        assert projection_calls == []
