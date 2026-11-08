"""Private fixture demo; print only protocol fields, never host/root metadata."""
import contextlib,io,json,pathlib,subprocess,sys,tempfile,tarfile
from types import SimpleNamespace
source=pathlib.Path(sys.argv[1]).resolve() if len(sys.argv)>1 else pathlib.Path(__file__).resolve().parents[3]
base='d0e8899ae8bf8553637e9859baae6bb4bb918338'
with tempfile.TemporaryDirectory() as t:
 scratch=pathlib.Path(t);old=scratch/'base';old.mkdir()
 archive=subprocess.run(['git','archive',base],cwd=source,capture_output=True,check=True)
 with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:tar.extractall(old,filter='data')
 root=scratch/'store';root.mkdir()
 probe=['--root',str(root),'--backend','files','--registry','files','crew','--local','--json','--display-snapshot']
 print('Same new display request against base and candidate; PRIVATE FILE REGISTRY.',flush=True)
 print('Candidate revision:',subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip(),flush=True)
 p=subprocess.run([sys.executable,'-c','import sys;from shantytown.cli import main;sys.exit(main())',*probe],cwd=old,capture_output=True,text=True)
 print('BASE:',base[:12],'exit',p.returncode,flush=True)
 print(p.stderr.strip().splitlines()[-1],flush=True);assert p.returncode==2
 sys.path.insert(0,str(source))
 from shantytown import crew_display as display
 args=SimpleNamespace(root=root,backend='files',registry='files',repo=None,local=True,json=True,count=False)
 def call():
  out=io.StringIO()
  with contextlib.redirect_stdout(out):rc=display.command(args)
  return rc,json.loads(out.getvalue())
 rc,value=call();print('CANDIDATE missing registry:',json.dumps(dict(exit=rc,complete=value['complete'],errors=value['errors'])),flush=True);assert rc!=0 and not value['complete']
 # A new root separates this deliberately repaired fixture from failed-read backoff.
 args.root=scratch/'ready';(args.root/'crew').mkdir(parents=True)
 calls=[];real=display.build_live
 def measured(a):calls.append(1);return real(a)
 display.build_live=measured
 rc,first=call();assert rc==0
 print('CANDIDATE valid empty registry:',json.dumps({k:first[k] for k in ['version','purpose','decision_eligible','complete','ttl_seconds']}),flush=True)
 rc,second=call();assert rc==0 and first['sampled_at']==second['sampled_at']
 args.json=False;args.count=True
 print('CANDIDATE second presentation:',flush=True);assert display.command(args)==0
 print('Three presentations; actual local refresh producer calls:',len(calls),flush=True);assert len(calls)==1
 print('No live service, peer, credential, activation or performance result is demonstrated.',flush=True)
