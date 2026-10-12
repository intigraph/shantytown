import json,re,sys
from datetime import datetime,timezone
from unittest.mock import patch
from shantytown import seeds_plate,deferrals
from shantytown.sd import StoreProof
proof=StoreProof('--quipu',None,'https://example.test','test','https://example.test/graph')
ids=['test-target-'+str(i) for i in range(59)]
rows=[dict(id='test-row-'+str(i),title='private condition fixture',status='deferred',notes='resume_when: closed:'+ids[i%59],priority=1,labels=[]) for i in range(436)]
requests=[]
def query(proof,q,timeout):
 requests.append(q)
 selected=list(dict.fromkeys(re.findall(r'<https://seeds.local/item/(test-target-\d+)>',q)))
 out=[]
 for ident in selected:
  n=int(ident.rsplit('-',1)[-1]);status='closed' if n%2 else 'open'
  if n%11==0: continue
  r=dict(graph=proof.graph,id=ident,status=status)
  if '?requested' in q:r['requested']=ident
  out.append(r)
  if n%13==0:out.append(dict(r,graph=proof.graph+'#seeds-ephemeral'))
  if n%17==0:r['status']='UNKNOWN-status'
 return dict(rows=out,count=len(out),truncated=False)
def run(mode):
 requests.clear()
 with patch.object(seeds_plate, '_query', query):
  if mode == 'before':
   cache={}
   for ident in ids:
    a=seeds_plate.closed_status(proof,ident)
    try:cache[ident]=a.exact()
    except Exception:cache[ident]=None
  else:cache=seeds_plate.closed_statuses(proof,ids)
  findings=deferrals.evaluate(rows,datetime(2026,10,12,10,23,tzinfo=timezone.utc),is_closed=cache.get)
 return len(requests),cache,[str(f) for f in findings]
print('Private offline fixture: 436 candidates, 59 condition targets; no service calls.')
a=run('before');b=run('after')
print('Before: %d exact-status queries' % a[0])
print('After:  %d bounded exact-status queries' % b[0])
assert a[1:] == b[1:]
print('Verdicts and %d findings identical.' % len(a[2]))
print('Positive controls: closed=True, open=False; missing/shadow/unsupported=UNKNOWN.')
print('Fresh pre-release single status read is separate; runtime adoption is unproven.')
