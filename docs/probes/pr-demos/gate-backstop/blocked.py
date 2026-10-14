from datetime import datetime,timezone
from tempfile import TemporaryDirectory
from shantytown.gate_backstop import Backstop
import json
results={}
for status in ['deferred','blocked']:
 with TemporaryDirectory() as root:
  calls=[]
  rows=[{'id':'waiter','status':status,'notes':'repo: same\nresume_when: closed:target','labels':[],'defer_until':None}, {'id':'target','status':'blocked','notes':'repo: same','labels':[],'updated_at':'2026-10-01T00:00:00Z'}]
  result=Backstop(root,datetime(2026,10,13,16,tzinfo=timezone.utc),lambda *a:calls.append(a) or True).run(rows,lambda _:None)
  results[status]={'events':len(calls),'reported':result}
print(json.dumps(results))
