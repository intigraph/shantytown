"""Roster admission shares candidate observation without dropping refusals."""
import pytest
from rdflib import Dataset, Literal, RDF, URIRef
from shantytown import seeds_plate as plate
from shantytown.sd import StoreProof


@pytest.mark.parametrize('active', [False, True])
@pytest.mark.parametrize('status', [None, 'open', 'in_progress', 'unrecognized'])
def test_default_roster_admission_uses_candidate_query(monkeypatch, status, active):
    graph = 'https://example.test/project/test'
    proof = StoreProof('fixture', None, 'https://example.test', 'test', graph)
    data = Dataset()
    target = data.graph(URIRef(graph))
    node = URIRef(plate.SEEDS + 'item/test-one')
    if status is not None:
        target.add((node, RDF.type, URIRef(plate.SCHEMA + 'Action')))
        for predicate, value in (
            (plate.SCHEMA + 'identifier', 'test-one'),
            (plate.SCHEMA + 'name', 'actual work'),
            (plate.SCHEMA + 'agent', 'crew/worker'),
            (plate.SEEDS + 'ontology/status', status),
            (plate.SEEDS + 'ontology/priority', 1),
            (plate.SEEDS + 'ontology/issueType', 'task'),
        ):
            target.add((node, URIRef(predicate), Literal(value)))
    # A foreign owner's unsupported status cannot poison this roster.
    foreign = URIRef(plate.SEEDS + 'item/test-foreign')
    target.add((foreign, RDF.type, URIRef(plate.SCHEMA + 'Action')))
    target.add((foreign, URIRef(plate.SCHEMA + 'agent'), Literal('other')))
    target.add((foreign, URIRef(plate.SEEDS + 'ontology/status'), Literal('unrecognized')))
    queries = []
    def query(_proof, text, timeout):
        queries.append(text)
        result = data.query(text)
        if result.type == 'ASK':
            return {'result': bool(result)}
        rows = [{str(k): v.toPython() if isinstance(v, Literal) else str(v)
                 for k, v in row.asdict().items()} for row in result]
        return {'rows': rows, 'count': len(rows), 'truncated': False}
    monkeypatch.setattr(plate, '_query', query)
    try:
        result = plate.owner_rows(proof, None, feed_owners=('worker',), capacity=True, active_only=active)
        assert result.complete is (status != 'unrecognized')
        selected = status in ('open', 'in_progress') and (not active or status == 'in_progress')
        if result.complete:
            assert [row['id'] for row in result.exact()] == (['test-one'] if selected else [])
        assert len(queries) == (2 if selected else 1)
        assert all(text.startswith('SELECT') for text in queries)
    finally:
        data.close()
