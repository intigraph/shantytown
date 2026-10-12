"""Closed conditions must not hydrate dependency trees or turn UNKNOWN into met."""
from datetime import datetime, timezone
import pytest

from shantytown import seeds_plate, deferrals
from shantytown.answer import Answer, PartialAnswer
from shantytown.feed_check import TrackerAdapter
from shantytown.sd import SdTracker, StoreProof

G = "https://example.test/project/test"
PROOF = StoreProof("--quipu", None, "https://example.test", "test", G)


def response(rows):
    return {"rows": rows, "count": len(rows), "truncated": False}


@pytest.mark.parametrize("status,expected", [("closed", True), ("open", False),
    ("in_progress", False), ("deferred", False), ("blocked", False), ("hooked", False)])
def test_exact_status_query_has_no_payload_or_dependency_reads(monkeypatch, status, expected):
    queries = []
    def query(proof, text, timeout):
        queries.append(text)
        return response([{"graph": G, "id": "test-a/b", "status": status}])
    monkeypatch.setattr(seeds_plate, "_query", query)
    assert seeds_plate.closed_status(PROOF, "test-a/b").exact() is expected
    assert len(queries) == 1
    assert "test-a%2Fb" in queries[0] and G + "#seeds-ephemeral" in queries[0]
    assert not any(word in queries[0] for word in ("description", "blockedOn", "comment", "notes"))


@pytest.mark.parametrize("rows", [[], [{"graph": G, "id": "other", "status": "closed"}],
    [{"graph": G, "id": "test-1", "status": "tombstone"}],
    [{"graph": G, "id": "test-1"}],
    [{"graph": G, "id": "test-1", "status": "closed"},
     {"graph": G + "#seeds-ephemeral", "id": "test-1", "status": "closed"}],
    [{"graph": G, "id": "test-1", "status": "closed"},
     {"graph": G + "#seeds-ephemeral", "id": "test-1"}]])
def test_bad_status_evidence_is_unknown_to_evaluator(monkeypatch, rows):
    monkeypatch.setattr(seeds_plate, "_query", lambda *a: response(rows))
    found = deferrals.evaluate([{"id": "test-waiter", "status": "deferred",
        "notes": "resume_when: closed:test-1"}], datetime.now(timezone.utc),
        is_closed=lambda identifier: seeds_plate.closed_status(PROOF, identifier).exact())
    assert len(found) == 1 and found[0].read_error and not found[0].met


def test_transport_failure_never_falls_back_to_hydration(monkeypatch):
    tracker = SdTracker(quipu=PROOF.quipu_url, prefix="test")
    monkeypatch.setattr(tracker, "prove_store", lambda: PROOF)
    monkeypatch.setattr(seeds_plate, "uses_native_schema", lambda *a, **kw: True)
    def fail(*args):
        raise OSError("unavailable")
    monkeypatch.setattr(seeds_plate, "_query", fail)
    monkeypatch.setattr(tracker, "_bd", lambda *a: pytest.fail("hydration fallback"))
    adapter = TrackerAdapter.__new__(TrackerAdapter)
    adapter.tracker, adapter.kind = tracker, "br"
    with pytest.raises(PartialAnswer, match="unavailable"):
        adapter.closed("test-1").exact()


def test_legacy_condition_uses_exact_full_show():
    adapter = TrackerAdapter.__new__(TrackerAdapter)
    adapter.tracker, adapter.kind = object(), "bd"
    adapter.show = lambda identifier: Answer.complete_read({"id": identifier, "status": "closed"}, how="fixture")
    assert adapter.closed("test-1").exact() is True


def test_alerter_uses_lean_condition_but_full_show_before_release(monkeypatch, tmp_path):
    from shantytown import feed_check, notify
    row = {"id": "test-waiter", "status": "deferred", "notes": "resume_when: closed:test-parent"}
    calls = []
    class Adapter:
        def deferred(self):
            return Answer.complete_read([dict(row)], how="fixture")
        def closed(self, identifier):
            calls.append(("closed", identifier))
            return Answer.complete_read(True, how="fixture")
        def show(self, identifier):
            calls.append(("show", identifier))
            assert identifier == "test-waiter"
            return Answer.complete_read(dict(row), how="fixture")
        def undefer(self, identifier):
            calls.append(("release", identifier))
            row.update(status="open", defer_until=None)
    monkeypatch.setattr(feed_check, "backend_adapter", lambda *a: Adapter())
    alerter = notify.DeferralAlerter(tmp_path, None, None, push=lambda *a: pytest.fail("unexpected ruling"))
    assert alerter.sweep() == []
    assert calls == [("closed", "test-parent"), ("show", "test-waiter"),
                     ("closed", "test-parent"),
                     ("release", "test-waiter"), ("show", "test-waiter")]
