import pathlib,tempfile,subprocess,os,json,shutil,sys,re
script=pathlib.Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory() as d:
 root=pathlib.Path(d);h=root/'home';h.mkdir();cache=h/'.cache/aegis-metric-fixtures/suite-control/home-escape-test/.cache/pre-commit';keep=[h/'workspace/public',h/'.cache/aegis-metric-fixtures/suite-control/home-escape-test/public',h/'workspace/home-escape-test/.cache/pre-commit/public'];gone=[cache/'repo-one',cache/'repo-two']
 for p in keep+gone:
  p.mkdir(parents=True);subprocess.run(['git','init','-q',str(p)],check=True);subprocess.run(['git','-C',str(p),'remote','add','origin','https://example.com/public.git'],check=True)
 conf=root/'patterns';conf.write_text('internal_host_re=forge\\.invalid\n');metrics=root/'scrub.prom';env=dict(os.environ,HOME=str(h),SCRUB_PATTERNS_FILE=str(conf),SCRUB_GUARD_TEXTFILE=str(metrics),SCRUB_GUARD_SOURCE_DIR=str(root/'neutral-source'))
 def sweep():
  r=subprocess.run(['bash',str(script),'--root',str(h)],env=env,capture_output=True,text=True,timeout=60);assert r.returncode==0,(r.stdout,r.stderr)
  vals={k:float(v) for k,v in re.findall(r'^(scrub_guard_\w+) ([\d.]+)$',metrics.read_text(),re.M)}
  assert all((p/'.git/hooks/pre-push').is_file() for p in keep)
  return {k:vals[k] for k in ['scrub_guard_repos_total','scrub_guard_armed_total','scrub_guard_missing_total','scrub_guard_excluded_total']}
 a=sweep()
 for p in gone:shutil.rmtree(p)
 b=sweep();print(json.dumps({'with_fixture_dependency_caches':a,'after_cache_cleanup':b,'all_three_noncache_repos_armed':True},sort_keys=True))
