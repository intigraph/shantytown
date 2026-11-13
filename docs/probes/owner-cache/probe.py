"""Finite loopback-only fixture; no production requests or credentials."""
import argparse,contextlib,hashlib,json,os,shutil,socket,subprocess,sys,time,urllib.request
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from shantytown import seeds_plate as plate,seeds_read_cache as cache
parser=argparse.ArgumentParser()
parser.add_argument('--fixture-root',type=Path,required=True)
args=parser.parse_args()
root=args.fixture_root.resolve();root.mkdir(exist_ok=True)
cli=shutil.which('quipu');server=shutil.which('quipu-server')
assert cli and server,'quipu and quipu-server must be installed'
env={k:v for k,v in os.environ.items() if not k.startswith(('QUIPU_','SEEDS_','ST_SEEDS_'))}
env.update(HOME=str(root),XDG_CONFIG_HOME=str(root/'config'),XDG_CACHE_HOME=str(root/'cache'),XDG_DATA_HOME=str(root/'data'))
os.environ.update(env)
for k in list(os.environ):
 if k.startswith(('QUIPU_','SEEDS_','ST_SEEDS_')):os.environ.pop(k)
os.environ['XDG_CACHE_HOME']=str(root/'cache')
graph='https://example.test/board';db=root/'fixture.db'
assert not db.exists(),'fixture already exists; preserve it'
ttl=root/'fixture.ttl'
ttl.write_text('\n'.join(f'<https://seeds.local/item/test-{i}> a <https://schema.org/Action>; <https://schema.org/identifier> "test-{i}"; <https://schema.org/name> "Work {i}"; <https://schema.org/agent> "worker"; <https://seeds.local/ontology/status> "in_progress"; <https://seeds.local/ontology/priority> 1; <https://seeds.local/ontology/issueType> "task" .' for i in range(30)))
subprocess.run([cli,'knot',str(ttl),'--graph',graph,'--db',str(db)],cwd=root,env=env,check=True,capture_output=True,timeout=20)
change=root/'ephemeral.ttl';change.write_text('<urn:ephemeral-control> <https://schema.org/name> "Control" .')
subprocess.run([cli,'knot',str(change),'--graph',graph+'#seeds-ephemeral','--db',str(db)],cwd=root,env=env,check=True,capture_output=True,timeout=20)
with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
log=root/'server.log'
with log.open('w') as sink:
 proc=subprocess.Popen([server,'--db',str(db),'--bind',f'127.0.0.1:{port}'],cwd=root,env=env,stdout=sink,stderr=sink)
 try:
  url=f'http://127.0.0.1:{port}';deadline=time.monotonic()+10
  while True:
   try:
    with urllib.request.urlopen(url+'/version',timeout=1) as r:version=json.load(r)
    break
   except OSError:
    if time.monotonic()>deadline:raise
    time.sleep(.1)
  proof=SimpleNamespace(quipu_url=url,graph=graph);original=cache.candidate_reads;cache._WATERMARK_MAX_AGE=0
  def observations():
   out=[]
   for line in log.read_text().splitlines():
    try:d=json.loads(line)
    except ValueError:continue
    if d.get('event')=='query_observation_end':out.append(d)
   return out
  print('Private fixture: 30 assigned items, both graphs, four reads with unrelated commits')
  print('BEFORE: same source with candidate retention disabled; AFTER: retention enabled')
  results={};queries=[];wire=plate._query_wire
  def capture(proof,q,t,**kw):queries.append(q);return wire(proof,q,t,**kw)
  plate._query_wire=capture
  for mode in ['before','after']:
   os.environ['XDG_CACHE_HOME']=str(root/mode)
   cache.candidate_reads=contextlib.nullcontext if mode=='before' else original
   start=len(observations());qstart=len(queries);rows=[]
   for i in range(4):
    change=root/'change.ttl';change.write_text(f'<urn:unrelated> <https://schema.org/description> "{mode}-{i}" .')
    subprocess.run([cli,'knot',str(change),'--graph',graph,'--db',str(db)],cwd=root,env=env,check=True,capture_output=True,timeout=15)
    ans=plate.owner_rows(proof,'worker',timeout=5);rows.append(sorted(r['id'] for r in ans.exact()))
   obs=observations()[start:];qs=queries[qstart:]
   results[mode]={'calls':4,'requests':len(qs),'store_held_ms':sum(r['store_held_ms'] for r in obs if r.get('store_held_ms') is not None),'observations':len(obs),'rows':rows,'query_hashes':[hashlib.sha256(q.encode()).hexdigest() for q in qs]}
  assert results['before']['rows']==results['after']['rows']
  assert results['after']['requests']<results['before']['requests']
  results['server_version']=version;results['server_pid']=proc.pid
  (root/'result.json').write_text(json.dumps(results,indent=2)+'\n')
  print(json.dumps({k:{f:v for f,v in d.items() if f not in ('rows','query_hashes')} for k,d in results.items() if k in ('before','after')}))
 finally:
  proc.terminate()
  try:proc.wait(timeout=5)
  except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
