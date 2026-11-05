"""aegis-bzc: the administrator ranking digest reads every cohort it needs, bounded.

The scheduled ranking used to call owner_rows(None, include_deferred=True),
which owner_rows refuses before any query, so every digest was PartialAnswer.
"""

import pytest

from shantytown import seeds_plate
from shantytown.answer import PartialAnswer
from shantytown.sd import SdTracker, StoreProof

G = "https://example.test/project/test"
EPH = G + "#seeds-ephemeral"
PROOF = StoreProof("--quipu", None, "https://example.test", "test", G)


def answer(rows):
    return {"rows": rows, "count": len(rows), "truncated": False}


def board():
    from rdflib import Dataset, Literal, RDF, URIRef

    data = Dataset()
    schema = seeds_plate.SCHEMA
    seeds = seeds_plate.SEEDS
    items = (
        # name, graph, status, priority, owner, title
        ("open-free", G, "open", 1, None, "work"),
        ("open-owned", G, "open", 2, "worker", "work"),
        ("held", G, "hooked", 2, "worker", "work"),
        ("active", G, "in_progress", 1, "lead", "work"),
        ("active-eph", EPH, "in_progress", 3, "worker", "work"),
        ("p0-deferred-free", G, "deferred", 0, None, "work"),
        ("p0-blocked-free-eph", EPH, "blocked", 0, None, "work"),
        # Excluded cohorts: the digest never reads them.
        ("p0-deferred-owned", G, "deferred", 0, "worker", "work"),
        ("p1-blocked-free", G, "blocked", 1, None, "work"),
        ("closed", G, "closed", 0, None, "work"),
        ("tombstone", G, "tombstone", 0, None, "work"),
        ("message", G, "open", 0, None, "inbox: [from lead] hello"),
    )
    for name, graph, status, priority, owner, title in items:
        node = URIRef(seeds + "item/" + name)
        target = data.graph(URIRef(graph))
        target.add((node, RDF.type, URIRef(schema + "Action")))
        target.add((node, URIRef(schema + "identifier"), Literal(name)))
        target.add((node, URIRef(schema + "name"), Literal(title)))
        target.add((node, URIRef(seeds + "ontology/status"), Literal(status)))
        target.add((node, URIRef(seeds + "ontology/priority"), Literal(priority)))
        if owner is not None:
            target.add((node, URIRef(schema + "agent"), Literal(owner)))
    return data


def serve(monkeypatch, data, seen=None):
    def query(proof, text, timeout):
        if seen is not None:
            seen.append(text)
        return answer([{str(k): v.toPython() for k, v in row.asdict().items()}
                       for row in data.query(text)])
    monkeypatch.setattr(seeds_plate, "_query", query)


def test_reads_exactly_the_digest_cohorts_in_actual_rdf(monkeypatch):
    serve(monkeypatch, board())
    result = seeds_plate.ranking_rows(PROOF)
    assert result.complete
    assert sorted(r["id"] for r in result.exact()) == sorted([
        "open-free", "open-owned", "held", "active", "active-eph",
        "p0-deferred-free", "p0-blocked-free-eph"])


def test_empty_board_is_a_complete_empty_answer(monkeypatch):
    from rdflib import Dataset
    serve(monkeypatch, Dataset())
    assert seeds_plate.ranking_rows(PROOF).exact() == []


def test_indexed_shape_constants_before_type_and_explicit_limit(monkeypatch):
    seen = []
    serve(monkeypatch, board(), seen)
    seeds_plate.ranking_rows(PROOF, max_rows=50)
    discovery = seen[0]
    assert discovery.rstrip().endswith("LIMIT 51")
    action = f"?s a <{seeds_plate.SCHEMA}Action>"
    for branch in discovery.split(" UNION "):
        assert branch.index(f"<{seeds_plate.SEEDS}ontology/status>") < branch.index(action)
        if "ontology/priority" in branch:
            assert branch.index("ontology/priority") < branch.index("ontology/status")
    # One status-constant branch per cohort and graph; no status variable.
    assert discovery.count(" UNION ") + 1 == 2 * (len(seeds_plate.RANKING_ACTIVE)
                                                  + len(seeds_plate.RANKING_WAITING))
    assert "?status" not in discovery


def test_reaching_the_row_budget_is_partial_never_a_silent_cap(monkeypatch):
    serve(monkeypatch, board())
    result = seeds_plate.ranking_rows(PROOF, max_rows=6)    # 7 qualifying rows
    assert not result.complete
    assert "ranking candidate budget reached (6)" in result.caveat
    with pytest.raises(PartialAnswer):
        result.exact()
    # Exactly at the budget is still complete: the LIMIT is MAX+1.
    assert len(seeds_plate.ranking_rows(PROOF, max_rows=7).exact()) == 7


def test_candidate_that_changed_cohort_during_the_read_is_unknown(monkeypatch):
    data = board()
    real = data.query

    def query(proof, text, timeout):
        rows = [{str(k): v.toPython() for k, v in row.asdict().items()} for row in real(text)]
        if "?predicate" in text:  # field read: the deferred P0 was just assigned
            rows.append({"subject": seeds_plate.SEEDS + "item/p0-deferred-free", "graph": G,
                         "predicate": seeds_plate.SCHEMA + "agent", "value": "worker"})
        return answer(rows)
    monkeypatch.setattr(seeds_plate, "_query", query)
    result = seeds_plate.ranking_rows(PROOF)
    assert not result.complete and "changed ranking candidate" in result.caveat


@pytest.mark.parametrize("budget", [0, -1, True, "5"])
def test_invalid_budget_is_refused(monkeypatch, budget):
    serve(monkeypatch, board())
    assert not seeds_plate.ranking_rows(PROOF, max_rows=budget).complete


def test_owner_scoped_refusal_still_refuses_before_any_query(monkeypatch):
    """The refusal ranking used to hit is unchanged: no owner, no waiting work."""
    calls = []
    monkeypatch.setattr(seeds_plate, "_query", lambda *a, **k: calls.append(a) or answer([]))
    result = seeds_plate.owner_rows(PROOF, None, include_deferred=True, include_messages=False)
    assert not result.complete
    assert "waiting-work metadata requires an owner scope" in result.caveat
    assert calls == []


def test_tracker_ranking_rows_uses_the_cohort_reader(monkeypatch):
    serve(monkeypatch, board())
    tracker = SdTracker(quipu=PROOF.quipu_url, prefix="test")
    monkeypatch.setattr(tracker, "prove_store", lambda: PROOF)
    monkeypatch.setattr(tracker, "_use_remote_projection", lambda: True)
    monkeypatch.setattr(seeds_plate, "unblocked_ids",
                        lambda proof, rows, timeout=30: {r["id"] for r in rows})
    ready, rows = tracker.ranking_rows()
    assert {r["id"] for r in ready} == {"open-free", "open-owned"}
    assert len(rows) == 7
