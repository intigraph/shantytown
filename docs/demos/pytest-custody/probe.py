import json,os,subprocess,tempfile,sys
from pathlib import Path
source=Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory(prefix="v6r-custody-") as t:
 root=Path(t);home=root/"home";home.mkdir();tmp=home/"short-tmp";tmp.mkdir(mode=0o700);owned=tmp/("pytest-of-"+subprocess.check_output(["id","-un"],text=True).strip());owned.mkdir(mode=0o700);generation=owned/"pytest-0";generation.mkdir(mode=0o700);(owned/"pytest-current").symlink_to(generation)
 for d in [generation/"fixture",tmp/"ordinary"]:
  d.mkdir();subprocess.run(["git","init","-q",str(d)],check=True);subprocess.run(["git","-C",str(d),"remote","add","origin","https://example.org/fixture.git"],check=True)
 conf=root/"patterns";conf.write_text("internal_host_re=forge\\.invalid\n");metrics=root/"metrics.prom"
 env=dict(os.environ,HOME=str(home),SCRUB_PATTERNS_FILE=str(conf),SCRUB_GUARD_SOURCE_DIR=str(root/"neutral"),SCRUB_GUARD_TEXTFILE=str(metrics))
 r=subprocess.run(["bash",str(source),"--root",str(home)],env=env,capture_output=True,text=True)
 values={l.split()[0]:l.split()[1] for l in metrics.read_text().splitlines() if l and not l.startswith("#")};print(json.dumps({"exit":r.returncode,"public":values["scrub_guard_repos_total"],"armed":values["scrub_guard_armed_total"],"fixtures":values["scrub_guard_fixture_excluded_total"],"missing":values["scrub_guard_missing_total"],"ordinary_hook":(tmp/"ordinary/.git/hooks/pre-push").is_symlink()},sort_keys=True))
