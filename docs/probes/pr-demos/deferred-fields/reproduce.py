"""Frozen offline evaluation parity; no service reads or board mutation."""
import re
from datetime import datetime, timezone
from unittest.mock import patch
from shantytown import deferrals, seeds_plate
from shantytown.sd import StoreProof
from shantytown.answer import PartialAnswer

proof = StoreProof('--quipu', None, 'https://example.test', 'test', 'https://example.test/graph')
rows = [dict(id=f'test-{i:03}', title='Held fixture', status='open' if i==50 else 'deferred',
             priority=i%5, created_at='2026-10-01T00:00:00Z', updated_at='2026-10-02T00:00:00Z',
             assignee=None, labels=[], notes='resume_when: closed:test-gate',
             defer_until='2026-10-01T00:00:00Z', description='Unused body '*1000)
        for i in range(51)]
rows.sort(key=lambda r:(r['status']=='open',r['priority'],r['created_at'],r['id']))
fields={**seeds_plate.FIELDS, seeds_plate.SEEDS+'ontology/notes':'notes'}
inverse={value:key for key,value in fields.items()}
requests=[]
def query(proof,q,timeout):
    requests.append(q)
    if 'AS ?predicate' not in q:
        wire=[dict(subject=seeds_plate.SEEDS+'item/'+r['id'],graph=proof.graph) for r in rows]
    else:
        ids=set(re.findall(r'<https://seeds.local/item/([^>]+)>',q))
        wire=[dict(subject=seeds_plate.SEEDS+'item/'+r['id'],graph=proof.graph,predicate=inverse[k],value=v)
              for r in rows if r['id'] in ids for k,v in r.items()
              if k in inverse and v is not None and k!='labels']
    return dict(rows=wire,count=len(wire),truncated=False)
now=datetime(2026,10,12,tzinfo=timezone.utc)
print('$ PYTHONPATH=. python3 docs/probes/pr-demos/deferred-fields/reproduce.py')
print('Offline frozen fixture: 50 deferred + 1 dated-open; no service calls.')
before=deferrals.evaluate(rows,now,is_closed=lambda _:True)
with patch.object(seeds_plate,'_query',query):
    lean=seeds_plate.deferred_rows(proof).exact()
after=deferrals.evaluate(lean,now,is_closed=lambda _:True)
assert before==after and [r['id'] for r in rows]==[r['id'] for r in lean]
assert all('description' not in r for r in lean)
print(f'Before: full fixture rows -> {len(before)} findings.')
print(f'After: {len(requests)} bounded candidate/field reads -> {len(after)} identical findings.')
print('Order and condition notes preserved; unused bodies omitted.')
with patch.object(seeds_plate,'_query',side_effect=ValueError('controlled unreadable response')):
    try:seeds_plate.deferred_rows(proof).exact()
    except PartialAnswer:print('Unreadable control: UNKNOWN, no hydration fallback.')
    else:raise AssertionError('failure became empty success')
print('Source fixture only; natural pass count, deployment and hourly rate unproven.')
