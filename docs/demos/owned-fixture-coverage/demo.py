"""Same isolated two-repository input on base and candidate; no fleet sweep."""
import argparse, json, os, shutil, subprocess, tempfile
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('--base',default='57092b9918437ad9278d83b71ce74e8cc4c99647');a=p.parse_args()
repo=Path(__file__).resolve().parents[3]

def run(command,**kw):
    return subprocess.run(command,check=True,capture_output=True,text=True,**kw).stdout

with tempfile.TemporaryDirectory() as tmp:
    for mode in ['base','candidate']:
        stage=Path(tmp)/mode;stage.mkdir()
        scripts=stage/'scripts';scripts.mkdir()
        for name in ['install-scrub-guard.sh','pre-push-scrub-guard.sh','pre-push-gitleaks.sh']:
            out=scripts/name
            if mode=='base':out.write_text(run(['git','show',f'{a.base}:scripts/{name}'],cwd=repo))
            else:shutil.copyfile(repo/'scripts'/name,out)
            out.chmod(0o755)
        home=stage/'home';home.mkdir()
        suite=home/'.cache/aegis-metric-fixtures/suite-abcd1234';suite.mkdir(parents=True);suite.chmod(0o700)
        for target in [home/'ordinary',suite/'fixture']:
            target.mkdir();run(['git','init','-q',str(target)]);run(['git','-C',str(target),'remote','add','origin','https://example.org/repository.git'])
        conf=stage/'patterns';conf.write_text('internal_host_re=forge\\.invalid\n')
        metrics=stage/'coverage.prom'
        env=dict(os.environ,HOME=str(home),SCRUB_PATTERNS_FILE=str(conf),SCRUB_GUARD_SOURCE_DIR=str(stage/'neutral'),SCRUB_GUARD_TEXTFILE=str(metrics))
        run(['bash',str(scripts/'install-scrub-guard.sh'),'--root',str(home)],env=env)
        values={s.split()[0]:int(s.split()[1]) for s in metrics.read_text().splitlines() if s.startswith(('scrub_guard_repos_total ','scrub_guard_armed_total ','scrub_guard_fixture_excluded_total '))}
        expected=2 if mode=='base' else 1
        assert values['scrub_guard_repos_total']==expected and values['scrub_guard_armed_total']==expected,values
        if mode=='candidate':assert values['scrub_guard_fixture_excluded_total']==1,values
        print(json.dumps({'revision':a.base if mode=='base' else 'candidate source','scope':'isolated same two-repository fixture','public_repos':values['scrub_guard_repos_total'],'armed':values['scrub_guard_armed_total'],'owned_fixtures':values.get('scrub_guard_fixture_excluded_total','metric absent on base')},sort_keys=True))
