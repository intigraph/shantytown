import pathlib,subprocess,tempfile,os,sys,shutil,json
root=pathlib.Path(__file__).resolve().parents[2]
base='0a5cd6ac5083c8b86c1622b21d04375501e304c4';head='80bc60e'
old=subprocess.check_output(['git','-C',str(root),'show',base+':.github/workflows/release.yml'],text=True);new=(root/'.github/workflows/release.yml').read_text()
def block(s):
 lines=s.splitlines();a=lines.index('      - name: Tag matches the declared version');b=next(i for i in range(a+1,len(lines)) if lines[i]=='        run: |');out=[]
 for l in lines[b+1:]:
  if l and not l.startswith('          '):break
  out.append(l[10:] if l else '')
 return '\n'.join(out)+'\n'
print('Sandbox: actual tag/identity shell gates; no release API writer',flush=True)
print('Base '+base+'; candidate source '+head,flush=True)
with tempfile.TemporaryDirectory() as t:
 p=pathlib.Path(t);(p/'bin').mkdir();shutil.copy2(sys.executable,p/'bin/python');(p/'pyproject.toml').write_text('[project]\nversion="0.4.1"\n')
 for cmd in [['git','init','-q'],['git','add','.'],['git','-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','fixture']]:subprocess.run(cmd,cwd=p,check=True,capture_output=True)
 sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=p,text=True).strip()
 for case,trigger,want in [('valid identity',sha,(0,0)),('wrong triggering commit','wrong-sha',(0,1))]:
  print('Input: '+case,flush=True)
  env=dict(os.environ,PATH=str(p/'bin')+':'+os.environ['PATH'],RELEASE_TAG='v0.4.1',GITHUB_REF_NAME='v0.4.1',GITHUB_SHA=trigger)
  exits=[]
  for name,s in [('base',old),('candidate',new)]:
   r=subprocess.run(['bash','-euo','pipefail','-c',block(s)],cwd=p,env=env,capture_output=True,text=True);exits.append(r.returncode);print(name+': exit '+str(r.returncode)+' '+(r.stdout+r.stderr).strip(),flush=True)
  assert tuple(exits)==want
print('PASS: valid identity preserved; wrong triggering commit newly refused',flush=True)
