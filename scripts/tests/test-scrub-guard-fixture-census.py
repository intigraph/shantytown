#!/usr/bin/env python3
"""CI control: fixture cleanup must preserve the fleet scrub census."""
# arming: ci; executed beside the installer selftest in every Python matrix job.
import os,pathlib,subprocess,sys,tempfile,shutil,re
source=pathlib.Path(sys.argv[1]).resolve() if len(sys.argv)>1 else pathlib.Path(__file__).resolve().parents[1]/"install-scrub-guard.sh"
with tempfile.TemporaryDirectory(prefix='wu-scrub-census-') as t:
 p=pathlib.Path(t);home=p/'home';home.mkdir();src=p/'source';src.mkdir()
 for n in ('install-scrub-guard.sh','pre-push-scrub-guard.sh','pre-push-gitleaks.sh'):shutil.copy2(source.parent/n,src/n)
 conf=p/'patterns.conf';conf.write_text('internal_host_re=forge\\.example\n')
 metrics=p/'scrub.prom';env=dict(os.environ,HOME=str(home),SCRUB_PATTERNS_FILE=str(conf),SCRUB_GUARD_DEFAULT_TEXTFILE=str(metrics))
 real=home/'workspace/real';fixture=home/'.cache/aegis-metric-fixtures/suite-fixture/repo';adjacent=home/'.cache/aegis-metric-fixtures-adjacent/repo'
 for r in (real,fixture,adjacent):
  r.mkdir(parents=True);subprocess.run(['git','init','-q',str(r)],check=True);subprocess.run(['git','-C',str(r),'remote','add','origin','https://github.com/example/fixture.git'],check=True)
 def sweep(args=()):
  r=subprocess.run([str(src/'install-scrub-guard.sh'),*args],env=env,text=True,capture_output=True);assert r.returncode==0,r.stderr+r.stdout
  data={k:int(v) for k,v in re.findall(r'^(scrub_guard_\w+) (\d+)$',metrics.read_text(),re.M)};return data
 before=sweep();shutil.rmtree(fixture.parent);after=sweep();print({'before':before['scrub_guard_repos_total'],'after':after['scrub_guard_repos_total'],'excluded_before':before['scrub_guard_excluded_total'],'excluded_after':after['scrub_guard_excluded_total']})
 assert before['scrub_guard_repos_total']==after['scrub_guard_repos_total']==2,'fixture lifecycle must not change estate census; real and adjacent namespace must remain counted'
 assert before['scrub_guard_excluded_total']==1 and after['scrub_guard_excluded_total']==0
 fixture.mkdir(parents=True);subprocess.run(['git','init','-q',str(fixture)],check=True);subprocess.run(['git','-C',str(fixture),'remote','add','origin','https://github.com/example/fixture.git'],check=True)
 scoped=sweep(('--root',str(fixture)));assert scoped['scrub_guard_repos_total']==after['scrub_guard_repos_total'],'scoped run changed fleet gauge'
 check=subprocess.run([str(src/'install-scrub-guard.sh'),'--root',str(fixture),'--check'],env=env,text=True,capture_output=True);assert check.returncode==0 and 'public armed: 1' in check.stdout,check.stdout+check.stderr
 print('PASS: real + adjacent controls counted; fixture excluded with lifecycle-stable census; explicit scoped fixture remains armable')
