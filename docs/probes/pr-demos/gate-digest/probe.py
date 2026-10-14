import sys,json,tempfile
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from shantytown.gate_backstop import Backstop
now=datetime(2026,10,13,16,tzinfo=timezone.utc)
rows=[]
for i in range(24):
 rows.extend([{'id':f'wait-{i}','status':'blocked','notes':f'repo: paper\nresume_when: closed:target-{i}'},{'id':f'target-{i}','status':'blocked','notes':'repo: source','updated_at':'2026-10-08T00:00:00Z'}])
with tempfile.TemporaryDirectory() as root:
 calls=[]
 first=Backstop(root,now,lambda *a:calls.append(a) or True).run(rows,lambda _:None)
 turns=len(calls)
 second=Backstop(root,now,lambda *a:calls.append(a) or True).run(rows,lambda _:None)
 print(json.dumps({'first_events':len(first),'first_admin_turns':turns,'second_events':len(second),'second_admin_turns':len(calls)-turns,'positive_24_stalled_chains':True,'private_fixture_only':True}))
with tempfile.TemporaryDirectory() as root:
 v=rows[:2];v[0]['notes']+='\ngate_verdict: Real dependency, keep gate\ngate_verdict_by: sattler\ngate_verdict_at: 2026-10-13T15:00:00Z'
 calls=[];result=Backstop(root,now,lambda *a:calls.append(a) or True).run(v,lambda _:None)
 print(json.dumps({'recent_verdict_admin_turns':len(calls),'recent_verdict_events':len(result)}))
