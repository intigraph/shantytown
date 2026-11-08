"""Execute the shipped SPARQL against a private named graph, not a fake sorter."""
from pathlib import Path

from rdflib import Dataset, Graph, Literal, Namespace, URIRef
from rdflib.namespace import XSD
import pytest


@pytest.mark.parametrize("due, datatype", [
    ("2026-11-07T00:00:00Z", XSD.dateTime),
    ("2026-11-07", XSD.date),
    ("2026-11-07Z", XSD.date),
    ("2026-11-07T03:00:00+03:00", XSD.dateTime),
])
def test_shipped_query_orders_due_and_preserves_legacy_owner_scope(due, datatype):
    q = Namespace("https://quipu.dev/ontology/")
    schema = Namespace("https://schema.org/")
    seeds = Namespace("https://seeds.local/ontology/")
    ical = Namespace("http://www.w3.org/2002/12/cal/ical#")
    source = Graph().parse(Path(__file__).parents[1] / "queries/seeds-work-rank-v1.ttl")
    template = str(source.value(URIRef("urn:quipu:query:seeds_work_rank_v1"), q.sparqlTemplate))
    params = dict(board="urn:test:board", owner="worker", now="2026-11-08T00:00:00Z")
    ids = ["old", "due", "foreign", "future", "native"]
    params.update({f"id{i:02}": ids[i] if i < len(ids) else "" for i in range(64)})
    for key, value in params.items():
        template = template.replace("{" + key + "}", value)
    data = Dataset()
    board = data.graph(URIRef(params["board"]))
    for ident, owner, created, due_value in (
        ("old", "crew/worker", "2026-10-01T00:00:00Z", None),
        ("native", URIRef("https://seeds.local/principal/worker"), "2026-10-02T00:00:00Z", None),
        ("due", None, "2026-11-01T00:00:00Z", due),
        ("foreign", "crew/other", "2026-09-01T00:00:00Z", None),
        ("future", None, "2026-11-01T00:00:00Z", "2026-12-01T00:00:00Z"),
    ):
        item = URIRef("urn:item:" + ident)
        for predicate, value in (
            # The actual native reader uses schema:version. A made-up
            # s:revision fixture would let a query that reads no live item pass.
            (schema.identifier, Literal(ident)), (schema.version, Literal(2)),
            (seeds.priority, Literal(1)), (seeds.status, Literal("open")),
            (schema.dateCreated, Literal(created, datatype=XSD.dateTime)),
        ):
            board.add((item, predicate, value))
        if owner:
            board.add((item, schema.agent, owner if isinstance(owner, URIRef) else Literal(owner)))
        if due_value:
            board.add((item, ical.due, Literal(due_value,
                datatype=datatype if ident == "due" else XSD.dateTime)))
    rows = list(data.query(template))
    assert [str(row.id) for row in rows] == ["due", "future", "old", "native"]
    assert all(int(row.revision) == 2 and str(row.sampled_at) == params["now"] for row in rows)
    assert all(row.created_at.datatype in (None, XSD.string) for row in rows)
    assert str(rows[-1].assignee) == "worker"
    assert str(rows[-2].assignee) == "crew/worker"
    # This is the original live-empty defect, not an expected empty fixture.
    assert list(data.query(template.replace("schema:version ?revision", "s:revision ?revision"))) == []
