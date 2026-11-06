import ast, hashlib, json, os, pathlib, subprocess, tarfile, tempfile
repo=pathlib.Path(__file__).resolve().parents[3]
base='0489a18d5e7ad914d1d0339e1e7dca7248b626b9'
name='test_deferral_sweep_executes_next_tend_after_slow_inbox_prefix'
source=(repo/'tests/test_tend.py').read_text()
node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name==name)
probe=ast.get_source_segment(source,node).replace('assert counts == [0, 1, 1, 2]', 'print("OBSERVED_COUNTS=" + json.dumps(counts), file=__import__("sys").__stdout__)\n    assert counts == [0, 1, 1, 2]')
print('Input: four real tend calls; simulated inbox cost130s; budget120s; respawn-first asserted')
print('BASE='+base)
with tempfile.TemporaryDirectory(prefix='uta-rotation-demo-') as td:
 root=pathlib.Path(td)
 archive=root/'base.tar'
 with archive.open('wb') as f: subprocess.run(['git','-C',str(repo),'archive',base],stdout=f,check=True)
 for arm in ('base','candidate'):
  dest=root/arm;dest.mkdir()
  with tarfile.open(archive) as f:f.extractall(dest,filter='data')
  if arm=='candidate':
   for rel in ('shantytown/cli.py','shantytown/sweep_rotation.py'):
    data=(repo/rel).read_bytes();(dest/rel).write_bytes(data)
    print('CANDIDATE_SHA256 '+rel+' '+hashlib.sha256(data).hexdigest())
  with (dest/'tests/test_tend.py').open('a') as f:f.write('\n\n'+probe+'\n')
  env=dict(os.environ);env['PYTHONPATH']=str(dest)
  r=subprocess.run(['/usr/bin/python3','-B','-m','pytest','-q','-s','tests/test_tend.py::'+name],cwd=dest,env=env,text=True,capture_output=True)
  lines=[line for line in r.stdout.splitlines() if line.startswith('OBSERVED_COUNTS=')]
  assert len(lines)==1,(arm,r.returncode,r.stdout[-2000:],r.stderr[-1000:])
  counts=json.loads(lines[0].split('=',1)[1])
  expected=[0,0,0,0] if arm=='base' else [0,1,1,2]
  assert counts==expected,(arm,counts)
  assert r.returncode==(1 if arm=='base' else 0),(arm,r.returncode)
  print(arm+': cumulative deferral-sweep executions '+str(counts)+'; test exit '+str(r.returncode)+(' (expected baseline failure)' if arm=='base' else ''))
print('DEMO PASS: same fixture0/4 ->2/4 executions; synthetic source proof, not installed acceptance')
