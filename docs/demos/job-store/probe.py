import json,tempfile,os
from pathlib import Path
from types import SimpleNamespace
from shantytown import cli,jobs
from shantytown.events import FilesEvents
with tempfile.TemporaryDirectory() as d:
 root=Path(d)
 (root/'crew').mkdir()
 (root/'crew'/'boss.json').write_text(json.dumps({'role':'administrator','pane':'private-fixture'}))
 (root/'shantytown.toml').write_text('[env]\nSHANTY_BACKEND="seeds"\n')
 jdir=root/'jobs';jdir.mkdir()
 (jdir/'nudge.toml').write_text('[trigger]\nevery="1h"\n[action]\ninbox="boss"\ndurable=true\nmessage="fixture"\n[retry]\nmax=0\n')
 a=SimpleNamespace(root=root,root_how='--root',backend=None,repo=None,registry='files',name='nudge',jobs_sub='check',graph=None)
 # Routing MUST NOT infer a work board from QUIPU_SERVER.
 os.environ['QUIPU_SERVER']='http://ontology.example.invalid'
 try:
  cli._tracker(a)._location()
  missing='incorrectly admitted'
 except Exception as e: missing=type(e).__name__
 check_rc=cli._cmd_jobs(a)
 cli._job_st=lambda *_a:(cli.REFUSED,'StoreUnproven: fixture backend unreachable')
 runner=cli._jobs_runner(a)
 lines=runner.sweep()
 events=FilesEvents(root/'events').pending('boss')
 print(json.dumps({'missing_route':missing,'check_rc':check_rc,'terminal_events':len(events),'event_detail':[e.detail for e in events],'lines':lines},sort_keys=True))
