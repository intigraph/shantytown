"""The real stop hook changes pickup without stealing or preempting work."""
from types import SimpleNamespace

from shantytown import backlog_rank, feed_check, stop_event
from shantytown.answer import Answer
from shantytown.sd import SdTracker
from test_haul import _run


def test_completed_anchor_claims_unowned_p1_before_owned_p2(monkeypatch, capsys):
    low = dict(id="low", revision=2, priority=2, assignee="billy", status="open")
    high = dict(id="high", revision=5, priority=1, assignee=None, status="open")
    rows = {row["id"]: row for row in (low, high)}
    claims = []
    class Tracker(SdTracker):
        def __init__(self):
            pass
        def haul_active_rows(self, owner):
            return Answer.complete_read([], how="completed anchor fixture")
        def prove_store(self):
            return SimpleNamespace(graph="urn:board")
        def stranded_read(self, ident):
            return dict(rows[ident])
        def claim_ranked_pickup(self, row, owner):
            claims.append((row["id"], row["revision"], owner))
            return True
    original = stop_event.deployment_default
    monkeypatch.setattr(stop_event, "deployment_default", lambda root, key:
                        "1" if key == "SHANTY_BACKLOG_PICKUP" else original(root, key))
    monkeypatch.setattr(stop_event, "_my_shells", lambda *args: 0)
    monkeypatch.setattr(feed_check, "_br_tracker", lambda *args: Tracker())
    monkeypatch.setattr(feed_check, "startable_here", lambda root, reg, rows: rows)
    monkeypatch.setattr(feed_check, "haul_governor_verdict", lambda *args: None)
    monkeypatch.setattr(backlog_rank, "ask", lambda root, name, params, **kw:
                        [dict(row, sampled_at=params["now"]) for row in (high, low)])
    legacy_claims = []
    rc, block = _run(monkeypatch, capsys, ready=[low, high], claims=legacy_claims)
    assert rc == 0 and "high" in block["reason"]
    assert claims == [("high", 5, "billy")]
    assert legacy_claims == []  # no second blind status write invalidates CAS evidence
    assert low["assignee"] == "billy" and low["status"] == "open"
