import sys,json,tempfile
from pathlib import Path
from datetime import datetime,timezone
sys.path.insert(0,sys.argv[1])
from shantytown.notify import DeferralAlerter
from shantytown.dispatch import Dispatcher,DeferRefused
from shantytown.files import FilesTracker,FilesRegistry
from shantytown.tmux import NullPanes
now=datetime(2026,10,13,16,tzinfo=timezone.utc)
with tempfile.TemporaryDirectory() as root:
 p=Path(root); calls=[]
 waiter={'id':'aegis-s9sjf.8','status':'deferred','priority':1,'notes':'resume_when: closed:aegis-i7xl1x.1','title':'Merge paper','updated_at':'2026-10-09T03:10:00Z'}
 target={'id':'aegis-i7xl1x.1','status':'deferred','priority':2,'title':'Unrelated release','updated_at':'2026-10-08T00:00:00Z','notes':''}
 details={x['id']:x for x in [waiter,target]}
 alert=DeferralAlerter(p,None,None,read=lambda:[waiter],show=lambda i:details[i],now=now,push=lambda *a:calls.append(a[-1]) or 'sattler')
 alert.sweep(); first=len(calls); alert.sweep(); second=len(calls)
 tr=FilesTracker(p/'items'); reg=FilesRegistry(p/'crew')
 tr.update(waiter['id'],status='open',title='Merge paper',priority=1)
 tr.update(target['id'],status='open',title='Unrelated release',priority=2)
 try:
  Dispatcher(reg,tr,NullPanes()).defer(waiter['id'],'bead','resume_when: closed:'+target['id'],dry_run=True)
  refused=False
 except DeferRefused as exc: refused=True; print('REFUSAL',str(exc),file=sys.stderr)
 print(json.dumps({'unreasoned_gate_refused':refused,'exact_chain_events_first_pass':first,'exact_chain_events_two_passes':second,'positive_control_target_status':details[target['id']]['status'],'private_fixture_only':True}))
