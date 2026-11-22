"""aegis-8dda.1 P1: operations records leave plates, rank, feed, counts and reminders."""
from datetime import datetime, timezone

import pytest

from shantytown import seeds_plate
from shantytown.inbox import is_ops_record, is_unfeedable
from shantytown.overdue import findings
from shantytown.plate_capacity import real_work
from shantytown.priority_advisory import workable
from shantytown.sd import StoreProof
from shantytown.stranded_work import eligible

G = "https://example.test/project/test"
PROOF = StoreProof("--quipu", None, "https://example.test", "test", G)
NOW = datetime(2026, 1, 2, tzinfo=timezone.utc)

OPS_ROWS = [
    dict(id="a-1", title="Recurring alarm: disk", labels=["recurring-alarm", "recurring-class:x"]),
    dict(id="a-2", title="Repo health: quipu", labels=["Repo-Health"]),
    dict(id="a-3", title="escalation[high]: x", labels=["gt:escalation", "escalation-record"]),
    dict(id="a-4", title="P0 orphaned duty: keeper", labels=["orphaned-duty"]),
    dict(id="a-5", title="anything", labels=[], issue_type="ops"),
]
WORK = dict(id="w-1", title="fix the disk alarm cause", labels=["quipu"], issue_type="bug")


def full(row, **extra):
    return dict(dict(status="open", priority=1, assignee="worker", due_at="2026-01-01T00:00:00Z"), **row, **extra)


@pytest.mark.parametrize("row", OPS_ROWS, ids=lambda r: r["id"])
def test_ops_records_are_excluded_everywhere(row, monkeypatch):
    monkeypatch.delenv("ST_OPS_RECORD_EXCLUSION", raising=False)
    row = full(row)
    assert is_ops_record(row)
    assert not real_work(row)
    assert not workable(row)
    assert not eligible(row)
    assert findings([row], NOW) == []


def test_label_path_reaches_the_feed_predicate(monkeypatch):
    monkeypatch.delenv("ST_OPS_RECORD_EXCLUSION", raising=False)
    assert is_unfeedable("Recurring alarm: disk", ["recurring-alarm"])


def test_a_linked_fix_stays_ordinary_work(monkeypatch):
    monkeypatch.delenv("ST_OPS_RECORD_EXCLUSION", raising=False)
    row = full(WORK)
    assert not is_ops_record(row) and real_work(row) and workable(row) and eligible(row)
    assert [f["id"] for f in findings([row], NOW)] == ["w-1"]


def test_rollback_switch_restores_previous_classification(monkeypatch):
    monkeypatch.setenv("ST_OPS_RECORD_EXCLUSION", "0")
    row = full(OPS_ROWS[1])
    assert not is_ops_record(row) and real_work(row) and workable(row)
    assert seeds_plate.ops_record_filter() == ""


def _dataset():
    rdflib = pytest.importorskip("rdflib")
    data = rdflib.Dataset()
    graph = data.graph(rdflib.URIRef(G))
    schema, seeds = seeds_plate.SCHEMA, seeds_plate.SEEDS
    for index, (label, kind) in enumerate([(None, "task"), ("recurring-alarm", "bug"), ("REPO-HEALTH", "task"),
                                           (None, "ops"), ("quipu", "bug")]):
        s = rdflib.URIRef(seeds + "item/t-" + str(index))
        graph.add((s, rdflib.RDF.type, rdflib.URIRef(schema + "Action")))
        graph.add((s, rdflib.URIRef(seeds + "ontology/status"), rdflib.Literal("open")))
        graph.add((s, rdflib.URIRef(seeds + "ontology/priority"), rdflib.Literal(1)))
        graph.add((s, rdflib.URIRef(schema + "identifier"), rdflib.Literal("t-" + str(index))))
        graph.add((s, rdflib.URIRef(schema + "name"), rdflib.Literal("item " + str(index))))
        graph.add((s, rdflib.URIRef(seeds + "ontology/issueType"), rdflib.Literal(kind)))
        if label:
            graph.add((s, rdflib.URIRef(schema + "keywords"), rdflib.Literal(label)))
    return data


def test_native_counts_drop_ops_records(monkeypatch):
    monkeypatch.delenv("ST_OPS_RECORD_EXCLUSION", raising=False)
    data = _dataset()

    def query(proof, text, timeout):
        rows = [{str(k): str(v) for k, v in row.asdict().items()} for row in data.query(text)]
        return dict(rows=rows, count=len(rows), truncated=False)
    monkeypatch.setattr(seeds_plate, "_query", query)
    assert seeds_plate.ready_count(PROOF, now=NOW) == 2
    monkeypatch.setenv("ST_OPS_RECORD_EXCLUSION", "0")
    assert seeds_plate.ready_count(PROOF, now=NOW) == 5
