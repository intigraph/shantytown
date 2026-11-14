"""Isolated source-library demonstration; no fleet reads, writes or process probes."""
import io,json,os,shutil,subprocess,sys,tarfile,tempfile
from pathlib import Path
if len(sys.argv)>1 and sys.argv[1]=='--child':
 sys.path.insert(0,sys.argv[2])
 from types import SimpleNamespace
 from shantytown.answer import Answer
 from shantytown.protocols import Agent
 from shantytown.inbox import FilesInbox
 from shantytown.stopped import FilesStops
 from shantytown.stranded_adapter import sweep
 from shantytown import deployment
 deployment.local_host=lambda root:'test-host'
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);cards={n:Agent(n,'administrator' if n=='admin' else 'worker',pane=n,host='test-host') for n in ['worker','admin']}
  registry=SimpleNamespace(all=lambda:Answer.complete_read(list(cards.values()),how='fixture'),get=lambda n:cards[n])
  rows=[dict(id=f'work-{i}',assignee='worker',status='deferred',priority=2,title='ASK operator: retained',labels=['desk'],defer_until='2999-01-01T00:00:00Z') for i in range(300)]
  rows += [dict(id=f'message-{i}',assignee='worker',status='open',priority=2,title='inbox: retained',labels=[]) for i in range(241)]
  tracker=SimpleNamespace(ranking_rows=lambda:([],[]),stranded_rows=lambda owners:rows)
  FilesStops(root/'stopped').record('worker',0)
  state=sys.argv[3];panes=SimpleNamespace(owner_state=lambda n:'live' if n=='admin' else state)
  sweep(root,registry,tracker,panes,FilesInbox(root/'inbox'),now=10)
  path=root/'stranded-work/attention.json';data=json.loads(path.read_text()) if path.exists() else {}
  print(json.dumps(dict(process=state,input_work=300,input_inbox=241,observed_work=len(data),release_due=sum(bool(x.get('release_due')) for x in data.values()),production_mutations=0)))
 sys.exit(0)
source=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parents[3]
base=sys.argv[2] if len(sys.argv)>2 else '0fb0cdc09135ee7492b2565cd1330bf89b58fc77'
with tempfile.TemporaryDirectory() as tmp:
 root=Path(tmp);old=root/'base';old.mkdir();head=root/'candidate';head.mkdir()
 raw=subprocess.check_output(['git','-C',str(source),'archive',base,'shantytown'])
 with tarfile.open(fileobj=io.BytesIO(raw)) as archive:archive.extractall(old,filter='data')
 shutil.copytree(source/'shantytown',head/'shantytown',ignore=shutil.ignore_patterns('__pycache__'))
 env=dict(os.environ,SHANTY_STRANDED_WORK='observe');env.pop('PYTHONPATH',None)
 results=[]
 for label,tree,state in [('base',old,'down'),('candidate',head,'down'),('candidate-live-control',head,'live')]:
  output=subprocess.check_output([sys.executable,str(Path(__file__).resolve()),'--child',str(tree),state],env=env,text=True)
  result=json.loads(output);results.append(result);print(label+': '+output.strip(),flush=True)
 assert [r['release_due'] for r in results]==[0,300,0]
 print('PASS: complete parked-work coverage; live process is never release-due; inbox recipients retained. Source fixture only, observe mode, no production mutation.')
