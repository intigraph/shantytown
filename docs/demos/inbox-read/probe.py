import argparse, json, os, pathlib, subprocess, sys, tempfile, time
p=argparse.ArgumentParser(); p.add_argument('source'); p.add_argument('--child'); p.add_argument('--count',type=int,default=96); a=p.parse_args()
if a.child:
 sys.path.insert(0,a.source)
 from shantytown import cli
 from shantytown.inbox import TrackerInbox
 from shantytown.protocols import WorkItem
 class Tracker:
  def get(self,id): return WorkItem(id=id,title='inbox: payload '+id,status='open',assignee='probe')
  def update(self,id,**fields):
   time.sleep(0.03)
   with open(a.child,'a') as f: f.write(id+'\n')
 rows=[Tracker().get('probe-'+str(i)) for i in range(a.count)]
 cli._inbox=lambda *_args,**_kw: TrackerInbox(Tracker(),lambda:rows)
 ns=argparse.Namespace(count=False,read=True,read_id=[])
 sys.exit(cli._inbox_read(ns,'probe'))
with tempfile.TemporaryDirectory() as d:
 ledger=pathlib.Path(d)/'ledger'
 start=time.monotonic()
 proc=subprocess.Popen([sys.executable,__file__,a.source,'--child',str(ledger),'--count',str(a.count)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 interrupted=False
 try: out,err=proc.communicate(timeout=1.2)
 except subprocess.TimeoutExpired:
  interrupted=True; proc.kill(); out,err=proc.communicate()
 closed=ledger.read_text().splitlines() if ledger.exists() else []
 print(json.dumps(dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),target='source checkout with synthetic tracker',initial=a.count,elapsed=round(time.monotonic()-start,3),exit=proc.returncode,interrupted=interrupted,closed=len(closed),unread=a.count-len(closed),stdout_bytes=len(out),stderr_bytes=len(err),payloads_visible=sum(('payload '+id).encode() in out for id in closed)),sort_keys=True))
 print(out.decode()); print(err.decode(),file=sys.stderr)
