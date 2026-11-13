"""Isolated library demo: no tracker or network access."""
import re
import sys

sys.path.insert(0, sys.argv[1])
from shantytown import seeds_plate as p
from shantytown.sd import StoreProof
from shantytown.answer import PartialAnswer

G = 'https://example.test/project/demo'
proof = StoreProof('fixture', None, 'https://example.test', 'test', G)
p.uses_native_schema = lambda *a, **kw: True
p.owner_shape_supported = lambda *a, **kw: True
p.seeds_read_cache.certify_projection = lambda *a: None
inverse = {v: k for k, v in p.FIELDS.items()}
for mode in ('dense', 'empty', 'truncated'):
    wires = {}
    for i in range(1100 if mode == 'dense' else 0 if mode == 'empty' else 1):
        identifier = f'test-dense-{i}'
        subject = p.SEEDS + 'item/' + identifier
        row = dict(id=identifier, title='work', status='open', assignee='worker',
                   priority=1, issue_type='task', created_at='2026-11-01T00:00:00Z',
                   updated_at='2026-11-01T00:00:00Z', lane='next', rank='1',
                   spec_version='v1', spec_ack_version='v1', spec_ack_actor='worker')
        wires[subject] = [dict(subject=subject, graph=G, predicate=inverse[k], value=v)
                          for k, v in row.items()]
    counts = []
    def query(_proof, text, _timeout):
        if '?predicate ?value' not in text:
            rows = [dict(subject=s, graph=G) for s in wires]
        else:
            selected = set(re.findall(r'<([^>]+/item/test-dense-\d+)>', text))
            rows = [field for s in selected for field in wires[s]]
            if mode == 'truncated':
                rows = rows[:1] * 10000
            rows = rows[:10000]
            counts.append(len(rows))
        return dict(rows=rows, count=len(rows), truncated=False)
    p._query = query
    try:
        rows = p.owner_rows(proof, None, feed_owners=('worker',)).exact()
        print(f'{mode}: COMPLETE {len(rows)} items; field replies {counts}')
    except PartialAnswer as error:
        print(f'{mode}: UNKNOWN {error}; field replies {counts}')
