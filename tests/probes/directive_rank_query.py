from pathlib import Path
import tempfile,subprocess,hashlib,sys,shutil
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from shantytown import directive_rank as dr
exe=shutil.which("quipu")
if not exe: raise SystemExit("quipu CLI unavailable; semantic control UNKNOWN")
a=dr.A;s=dr.SCHEMA;v=dr.SEEDS
with tempfile.TemporaryDirectory(prefix="g5dh-query-") as name:
 root=Path(name);db=root/"test.db"
 data="\n".join(f'<urn:d{i}> a <{a}Directive> ; '+(f'<{a}directiveKind> "{kind}" ; ' if kind else '')+f'<{a}trackedBy> <{a}{target}> .' for i,kind,target in [(1,"operator","direct"),(2,"operator","epic"),(3,"admin-ruling","admin"),(4,None,"missing"),(5,"operator","ordinary")])
 f=root/"root.ttl";f.write_text(data)
 def run(args):
  r=subprocess.run([exe,*args,"--db",str(db)],capture_output=True,text=True,timeout=15)
  assert r.returncode==0,r.stderr
  return r.stdout
 run(["knot",str(f)])
 facts=[f'<{v}item/epic> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <{s}Action> .',f'<{v}item/leaf> <{s}isPartOf> <{v}item/epic> .',f'<{v}item/epic> <{s}isPartOf> <{v}item/leaf> .',f'<{v}item/epic> <{v}ontology/issueType> "epic" .',f'<{v}item/epic> <{s}identifier> "epic" .',f'<{v}item/other> <{s}isPartOf> <{v}item/ordinary> .',f'<{v}item/ordinary> <{v}ontology/issueType> "task" .',f'<{v}item/ordinary> <{s}identifier> "ordinary" .']
 f=root/"project.nt";raw="\n".join(facts)+"\n";f.write_text(raw)
 run(["ingest",str(f),"--graph","urn:project","--timestamp","2026-11-28T00:00:00Z","--declare-count",str(len(facts)),"--declare-sha256",hashlib.sha256(raw.encode()).hexdigest(),"--format","nt"])
 q=dr.query("urn:project",{"direct","leaf","admin","missing","other"})
 out=run(["query",q]);print(out)
 rows={line.strip('"') for line in out.splitlines()[2:-2]};assert rows=={"direct","leaf"},repr(rows)
 mutant=q.replace(f'<{a}directiveKind> "operator" ; ','')
 out=run(["query",mutant]);assert 'admin' in out and 'missing' in out
 raw=f'<{v}item/epic> <{v}ontology/issueType> "task" .\n';f=root/"shadow.nt";f.write_text(raw)
 run(["ingest",str(f),"--graph","urn:project#seeds-ephemeral","--timestamp","2026-11-28T00:00:00Z","--declare-count","1","--declare-sha256",hashlib.sha256(raw.encode()).hexdigest(),"--format","nt"])
 out=run(["query",q]);assert {line.strip('"') for line in out.splitlines()[2:-2]}=={"direct"},out
 print("PASS shadowed ancestor suppressed")
 print("PASS direct+epic, admin/missing/non-epic negatives, cycle termination; operator-kind mutant changes rows")

