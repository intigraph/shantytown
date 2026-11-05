"""Compare fresh owner reads on identical private RDF data; no network calls."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile

from rdflib import Dataset, Literal, RDF, URIRef
from shantytown import seeds_plate
from shantytown.sd import StoreProof


def measure(module):
    graph = 'https://example.test/project/owner-readcut'
    proof = StoreProof('--quipu', None, 'https://example.test', 'demo', graph)
    data, calls = Dataset(), []
    target = data.graph(URIRef(graph))
    subject = URIRef(module.SEEDS + 'item/demo-work')
    target.add((subject, RDF.type, URIRef(module.SCHEMA + 'Action')))
    for key, value in [('identifier', 'demo-work'), ('name', 'ordinary work'),
                       ('agent', 'worker')]:
        target.add((subject, URIRef(module.SCHEMA + key), Literal(value)))
    target.add((subject, URIRef(module.SEEDS + 'ontology/status'), Literal('open')))
    target.add((subject, URIRef(module.SEEDS + 'ontology/priority'), Literal(1)))

    def query(_proof, text, _timeout):
        calls.append(text)
        result = data.query(text)
        if result.type == 'ASK':
            return {'result': bool(result.askAnswer)}
        rows = [{str(k): v.toPython() if isinstance(v, Literal) else str(v)
                 for k, v in row.asdict().items()} for row in result]
        return {'rows': rows, 'count': len(rows), 'truncated': False}

    original = module._query
    module._query = query
    try:
        populated = module.owner_rows(proof, 'worker').exact()
        populated_requests = len(calls)
        calls.clear()
        empty = module.owner_rows(proof, 'other').exact()
        empty_requests = len(calls)
        calls.clear()
        target.remove((subject, URIRef(module.SEEDS + 'ontology/status'), None))
        rejected = module.owner_rows(proof, 'worker')
        assert not rejected.complete
        return dict(ids=[row['id'] for row in populated], empty=empty,
                    populated_requests=populated_requests,
                    empty_requests=empty_requests,
                    missing_status_refused=not rejected.complete,
                    refusal_requests=len(calls))
    finally:
        module._query = original
        data.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True, help='reviewed baseline commit')
    args = parser.parse_args()
    source = subprocess.check_output(
        ['git', 'show', args.base + ':shantytown/seeds_plate.py'])
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'seeds_plate.py'
        path.write_bytes(source)
        spec = importlib.util.spec_from_file_location('shantytown._owner_readcut_base', path)
        base = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(base)
        before, after = measure(base), measure(seeds_plate)
    assert before['ids'] == after['ids'] == ['demo-work']
    assert before['empty'] == after['empty'] == []
    assert before['populated_requests'] == 3 and after['populated_requests'] == 2
    assert before['empty_requests'] == 2 and after['empty_requests'] == 1
    assert before['missing_status_refused'] and after['missing_status_refused']
    print(json.dumps({'before': before, 'after': after}, indent=2))


if __name__ == '__main__':
    main()
