"""Candidate-only exact-context fixture; no network or tracker writes."""
from types import SimpleNamespace
from unittest.mock import patch
from shantytown import work_context
from shantytown.protocols import WorkItem

item = WorkItem(id="test-123", title="Example task", status="open", assignee="reader",
                priority=2, description="", notes="Retained evidence exists",
                defer_until=None, open_blockers=(), due_at=None)
proof = SimpleNamespace(quipu_url="http://fixture.invalid", graph="urn:fixture:project")
tracker = SimpleNamespace(prove_store=lambda: proof)

def query(proof, sparql, timeout, *, verbose=False):
    if "aboutWorkItem" in sparql:
        return {"rows": [{"act": "urn:fixture:episode", "label": "Example evidence",
                          "when": "2026-01-01T00:00:00Z", "gist": "Identity finds linked evidence"}]}
    return {"rows": []}

with patch("shantytown.seeds_item.read_item", return_value=item), patch.object(work_context, "_query", query):
    print("Candidate fixture: exact identity, no semantic search needed")
    print(work_context.render(work_context.context(tracker, "test-123", onto="urn:fixture:")))
with patch("shantytown.seeds_item.read_item", return_value=item), patch.object(work_context, "_query", side_effect=TimeoutError("fixture read timeout")):
    print("\nNegative control: failed reads remain UNKNOWN")
    print(work_context.render(work_context.context(tracker, "test-123", onto="urn:fixture:")))
