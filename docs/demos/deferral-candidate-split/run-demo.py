#!/usr/bin/env python3
"""Private wire fixture: no HTTP, store, agent or scheduled sweep is invoked."""
import subprocess
import types
from shantytown import seeds_plate
from shantytown.answer import PartialAnswer
from shantytown.sd import StoreProof

BASE = '8f1d426bf91dd392937d00620739ff24069d634f'
source = subprocess.check_output(['git', 'show', BASE + ':shantytown/seeds_plate.py'], text=True)
before = types.ModuleType('shantytown._before_candidate_split')
before.__package__ = 'shantytown'
exec(compile(source, '<reviewed baseline>', 'exec'), before.__dict__)
proof = StoreProof('--quipu', None, 'https://example.test', 'test', 'https://example.test/graph')
subject = seeds_plate.SEEDS + 'item/test-one'
fields = {**seeds_plate.FIELDS, seeds_plate.SEEDS + 'ontology/notes': 'notes'}
values = dict(id='test-one', title='fixture', status='deferred', priority=1,
              created_at='2026-10-01T00:00:00Z', notes='resume_when: closed:test-two')
inverse = {v: k for k, v in fields.items()}

def probe(module):
    counts = []
    def query(_proof, text, timeout):
        if 'AS ?predicate' in text:
            rows = [dict(subject=subject, graph=proof.graph, predicate=inverse[k], value=v)
                    for k, v in values.items()]
        else:
            arms = text.count(' UNION ') + 1
            counts.append(arms)
            if arms > 1:
                raise ValueError('fixture rejects multi-arm candidate execution')
            rows = [dict(subject=subject, graph=proof.graph)]
        return dict(rows=rows, count=len(rows), truncated=False)
    original = module._query
    module._query = query
    try:
        rows = module.deferred_rows(proof, include_asks=True).exact()
        return 'COMPLETE', len(rows), counts
    except PartialAnswer:
        return 'UNKNOWN', 0, counts
    finally:
        module._query = original

old, new = probe(before), probe(seeds_plate)
assert old == ('UNKNOWN', 0, [16])
assert new == ('COMPLETE', 1, [1] * 16)
print('BEFORE: one 16-arm candidate -> UNKNOWN; no partial hydration')
print('AFTER: sixteen single-arm candidates -> COMPLETE, one deduplicated fixture item')
print('No HTTP request, production timing, scheduled sweep or server change demonstrated.')
