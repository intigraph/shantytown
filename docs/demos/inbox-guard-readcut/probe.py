"""Compare source revisions against the same private RDF inbox fixtures."""
import argparse
import json
import subprocess
import sys
import types

from rdflib import Dataset, Literal, RDF, URIRef
from shantytown.sd import StoreProof


def load(revision, label):
    source = subprocess.check_output(
        ['git', 'show', revision + ':shantytown/seeds_plate.py'], text=True)
    module = types.ModuleType('shantytown._inbox_demo_' + label)
    module.__package__ = 'shantytown'
    exec(compile(source, '<' + label + ' source>', 'exec'), module.__dict__)
    return module


def observe(module, scenario):
    graph = 'https://example.test/project/demo'
    proof = StoreProof('--quipu', None, 'https://example.test', 'demo', graph)
    data, requests = Dataset(), []
    if scenario != 'empty':
        target = data.graph(URIRef(graph))
        subject = URIRef(module.SEEDS + 'item/demo-receipt')
        target.add((subject, RDF.type, URIRef(module.SCHEMA + 'Action')))
        for predicate, value in [(module.SCHEMA+'identifier', 'demo-receipt'),
                                 (module.SCHEMA+'name', 'inbox: positive control'),
                                 (module.SCHEMA+'agent', 'worker'),
                                 (module.SEEDS+'ontology/status', 'open'),
                                 (module.SEEDS+'ontology/priority', 1)]:
            target.add((subject, URIRef(predicate), Literal(value)))
        if scenario == 'bad-status':
            bad = URIRef(module.SEEDS+'item/demo-ordinary-work')
            target.add((bad, RDF.type, URIRef(module.SCHEMA+'Action')))
            target.add((bad, URIRef(module.SCHEMA+'agent'), Literal('worker')))
            target.add((bad, URIRef(module.SEEDS+'ontology/status'), Literal('alien')))
    def query(_proof, text, timeout):
        requests.append(text)
        result = data.query(text)
        if result.type == 'ASK':
            return {'result': bool(result.askAnswer)}
        rows = [{str(k): v.toPython() if isinstance(v, Literal) else str(v)
                 for k,v in row.asdict().items()} for row in result]
        return {'rows': rows, 'count': len(rows), 'truncated': False}
    module._query = query
    try:
        answer = module.owner_rows(proof, 'worker', messages_only=True)
        return {'requests': len(requests), 'complete': answer.complete,
                'ids': sorted(row['id'] for row in answer.at_least())}
    finally:
        data.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', required=True)
    parser.add_argument('--candidate', default='HEAD')
    args = parser.parse_args()
    modules = [load(args.base, 'base'), load(args.candidate, 'candidate')]
    for scenario in ('populated', 'empty', 'bad-status'):
        before, after = [observe(module, scenario) for module in modules]
        assert before['ids'] == after['ids'] and before['complete'] == after['complete']
        expected = (3, 2) if scenario == 'populated' else (2, 1) if scenario == 'empty' else (1, 1)
        assert (before['requests'], after['requests']) == expected
        print(json.dumps({'fixture': scenario, 'before': before, 'after': after}), flush=True)
    print('Same rows and refusal; no production endpoint or installed-rate claim.')


if __name__ == '__main__':
    main()
