"""Execute the shipped SPARQL against a private named graph, not a fake sorter."""
from pathlib import Path

from rdflib import Dataset, Graph, Literal, Namespace, URIRef
from rdflib.namespace import XSD


def test_shipped_query_orders_due_and_preserves_legacy_owner_scope():
    q = Namespace("https://quipu.dev/ontology/")
    schema = Namespace("https://schema.org/")
    seeds = Namespace("https://seeds.local/ontology/")
    ical = Namespace("http://www.w3.org/2002/12/cal/ical#")
    source = Graph().parse(Path(__file__).parents[1] / "queries/seeds-work-rank-v1.ttl")
    template = str(source.value(URIRef("urn:quipu:query:seeds_work_rank_v1"), q.sparqlTemplate))
    params = dict(board="urn:test:board", owner="worker", now="2026-11-08T00:00:00Z")
    ids = ["old", "due", "foreign"]
    params.update({f"id{i:02}": ids[i] if i < len(ids) else "" for i in range(64)})
    for key, value in params.items():
        template = template.replace("{" + key + "}", value)
    data = Dataset()
    board = data.graph(URIRef(params["board"]))
    for ident, owner, created, due in (
        ("old", "crew/worker", "2026-10-01T00:00:00Z", None),
        ("due", None, "2026-11-01T00:00:00Z", "2026-11-07T00:00:00Z"),
        ("foreign", "crew/other", "2026-09-01T00:00:00Z", None),
    ):
        item = URIRef("urn:item:" + ident)
        for predicate, value in (
            (schema.identifier, Literal(ident)), (seeds.revision, Literal(2)),
            (seeds.priority, Literal(1)), (seeds.status, Literal("open")),
            (schema.dateCreated, Literal(created, datatype=XSD.dateTime)),
        ):
            board.add((item, predicate, value))
        if owner:
            board.add((item, schema.agent, Literal(owner)))
        if due:
            board.add((item, ical.due, Literal(due, datatype=XSD.dateTime)))
    rows = list(data.query(template))
    assert [str(row.id) for row in rows] == ["due", "old"]
    assert all(int(row.revision) == 2 and str(row.sampled_at) == params["now"] for row in rows)
