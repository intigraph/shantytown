"""Typed/ROOT reads declare primary transport before dispatch (az3d)."""
import io
import json
from types import SimpleNamespace

import pytest

from shantytown import seeds_item, seeds_plate, seeds_push_read, seeds_read_cache, work_context


GRAPH = "https://seeds.local/project/test"
ONTO = "https://ontology.example/"
SUBJECT = seeds_item.SEEDS + "item/test-one"
PROOF = SimpleNamespace(quipu_url="https://graph.example", graph=GRAPH)


class Tracker:
    timeout = 3

    def prove_store(self):
        return PROOF

    def _use_remote_projection(self):
        return True


def item_rows():
    fields = {
        seeds_item.TYPE: (seeds_item.SCHEMA + "Action", "iri"),
        seeds_item.SCHEMA + "identifier": ("test-one", seeds_item.XSD + "string"),
        seeds_item.SCHEMA + "name": ("https://literal.example/title", seeds_item.XSD + "string"),
        seeds_item.SEEDS + "ontology/status": ("open", seeds_item.XSD + "string"),
        seeds_item.SEEDS + "ontology/priority": ("1", seeds_item.XSD + "integer"),
    }
    return [{"graph": GRAPH, "s": SUBJECT, "p": p, "o": value, "kind": kind}
            for p, (value, kind) in fields.items()]


def fixture_rows(query):
    if "aboutWorkItem" in query:
        return [{"act": ONTO + f"episode/{i}", "label": f"e{i}",
                 "when": {"datatype": seeds_item.XSD + "dateTime",
                          "value": "2026-11-28T07:00:00Z"},
                 "gist": "https://literal.example/summary"} for i in range(8)]
    if "trackedBy" in query:
        return [{"ruling": ONTO + f"ruling/{i}", "type": ONTO + "Directive"}
                for i in range(8)]
    if "parentItem" in query:
        return [{"position": 2, "author": "https://literal.example/author",
                 "gist": "literal comment"}]
    return item_rows()


def install_wire(monkeypatch, calls):
    def wire(request, *, timeout):
        body = json.loads(request.data)
        assert body["verbose"] is True
        query = body["query"]
        label = request.get_header("X-quipu-agent")
        root = "aboutWorkItem" in query or "trackedBy" in query
        assert label == ("st-context-root" if root else "st-typed-cells")
        assert request.get_header("X-quipu-operation") == ("root-context" if root else "typed-cells")
        calls.append((label, query))
        rows = fixture_rows(query)
        response = io.BytesIO(json.dumps({"rows": rows, "count": len(rows),
                                         "truncated": False}).encode())
        response.status = 200
        return response
    monkeypatch.setattr(seeds_plate, "urlopen", wire)
    monkeypatch.setattr(seeds_read_cache, "read", lambda *a, **k: pytest.fail("typed cache"))
    def push(proof, query, timeout):
        if "aboutWorkItem" in query or "trackedBy" in query:
            raise ValueError("push read UNKNOWN: query exceeds complete projection scope")
        raise ValueError("push read UNKNOWN: lossless typed cells unsupported")
    monkeypatch.setattr(seeds_push_read, "read", push)


def test_context_sections_and_typed_cells_are_identical_with_push_on_and_off(monkeypatch):
    monkeypatch.setenv("QUIPU_AGENT", "inherited-caller")
    calls = []
    install_wire(monkeypatch, calls)
    renders = []
    for enabled in ("0", "1"):
        monkeypatch.setenv("ST_SEEDS_PUSH_READS", enabled)
        ctx = work_context.context(Tracker(), "test-one", onto=ONTO)
        assert ctx.item is not None
        assert ctx.item.title == "https://literal.example/title"
        assert not any(section.unknown for section in ctx.sections)
        assert [len(section.rows) for section in ctx.sections] == [1, 8, 8]
        renders.append(work_context.render(ctx).encode())
    assert renders[0] == renders[1]
    assert [label for label, _ in calls] == ["st-typed-cells", "st-typed-cells",
                                            "st-context-root", "st-context-root"] * 2


def test_declared_root_failure_is_unknown_without_retry_or_another_route(monkeypatch):
    monkeypatch.setenv("ST_SEEDS_PUSH_READS", "1")
    calls = []
    install_wire(monkeypatch, calls)
    good = seeds_plate._query_wire
    failures = []
    def fail_one(proof, query, timeout, *, verbose=False, declared_agent=None):
        if "aboutWorkItem" in query:
            failures.append(query)
            raise TimeoutError("declared ROOT read timed out")
        return good(proof, query, timeout, verbose=verbose, declared_agent=declared_agent)
    monkeypatch.setattr(seeds_plate, "_query_wire", fail_one)
    ctx = work_context.context(Tracker(), "test-one", onto=ONTO)
    assert len(failures) == 1
    assert ctx.sections[1].unknown == "TimeoutError: declared ROOT read timed out"
    assert len(ctx.sections[2].rows) == 8


def test_declared_typed_failure_does_not_retry_through_push(monkeypatch):
    monkeypatch.setenv("ST_SEEDS_PUSH_READS", "1")
    seen = []
    def fail(*args, **kwargs):
        seen.append(args)
        raise ValueError("typed result incomplete")
    monkeypatch.setattr(seeds_plate, "_query_wire", fail)
    monkeypatch.setattr(seeds_push_read, "read", lambda *a: pytest.fail("fallback"))
    with pytest.raises(ValueError, match="typed result incomplete"):
        seeds_item.read_item(Tracker(), "test-one")
    assert len(seen) == 1


def test_declared_typed_reads_preserve_the_expanded_wire_cells(monkeypatch):
    monkeypatch.setenv("ST_SEEDS_PUSH_READS", "1")
    rows = [{"iri": "https://example.org/value", "literal": {
        "value": "https://example.org/value", "datatype": seeds_item.XSD + "string"},
        "lang": {"value": "bonjour", "language": "fr"},
        "integer": 2}]
    monkeypatch.setattr(seeds_plate, "_query_wire", lambda *a, **k: {"rows": rows})
    assert seeds_plate.typed_cells_query(PROOF, "SELECT ?s WHERE { ?s ?p ?o } LIMIT 1", 3)["rows"] == rows


@pytest.mark.parametrize("reader", [seeds_plate.typed_cells_query, seeds_plate.root_context_query])
def test_declared_verbose_contract_cannot_be_downgraded(reader):
    with pytest.raises(ValueError, match="verbose"):
        reader(PROOF, "SELECT ?s WHERE { ?s ?p ?o } LIMIT 1", 3, verbose=False)
