"""Offline source demonstration. Model and quarantine are strict fixtures."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
p=argparse.ArgumentParser();p.add_argument('--source',required=True);a=p.parse_args()
sys.path.insert(0,str(Path(a.source).resolve()))
from shantytown import board_rank as rank
now=datetime(2026,11,4,13,tzinfo=timezone.utc)
policies={kind:dict(iri='urn:fixture:'+kind) for kind in rank.KINDS}
def row(i='fixture',priority=1,status='open'):
    return dict(id=i,title='ordinary maintenance',description='No personal need stated',
                priority=priority,status=status,assignee=None,labels=[],blocked_by=[])
class Client:
    def __init__(self):self.calls=[]
    def call(self,tool,arguments):
        self.calls.append(tool)
        return dict(request=dict(fixture=len(self.calls)),model='offline-fixture',usage={},
                    answer={'noul':.25} if tool=='jev_noul' else {'choice':'none-of-these','confidence':.5})
for status,priority in [('open',1),('deferred',0),('open',2)]:
    result=rank.propose([row(priority=priority,status=status)],policies,{},now=now)
    r=result['proposals'][0]
    print(json.dumps(dict(case='owner',priority=priority,status=status,needs_owner=r.get('needs_owner','UNAVAILABLE'),
                          reowner_down_only=r['reowner'],changes_applied=result['changes_applied']),sort_keys=True))
client=Client();sink=lambda _:{'verified':True}
if hasattr(rank,'semantic_benchmark'):
    cases=[dict(before=row('case'+str(i),priority=i%4),source='urn:fixture-label',rules=['urn:fixture-rule'],
                observed_at=now.isoformat(),owner_states={},owner_evidence='urn:fixture-owner',
                expected={'reowner':None,'flags':{'automation':False,'personal-need':False}}) for i in range(30)]
    result=rank.semantic_benchmark(cases,policies,client=client,inference_sink=sink)
    schema=result['schema']
else:
    result=rank.propose([row('case'+str(i),priority=i%4) for i in range(30)],policies,{},now=now,client=client,inference_sink=sink)
    schema='legacy combined path; no semantic-only entrypoint'
print(json.dumps(dict(case='fixture-tools',schema=schema,noul_calls=client.calls.count('jev_noul'),
                      rank_band_calls=client.calls.count('jev_choice'),live_calls=0,changes_applied=False),sort_keys=True))
