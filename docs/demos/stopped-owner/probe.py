"""A real stop command with fake panes and a disposable two-seed store."""
import sys,tempfile,json,io,contextlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,sys.argv[1])
from shantytown import cli
from shantytown.tmux import NullPanes
from shantytown.inbox import FilesInbox
from shantytown.answer import Answer
from shantytown.stopped import FilesStops
with tempfile.TemporaryDirectory(prefix='xgt-stop-') as d:
 root=Path(d);(root/'crew').mkdir()
 for name,card in {'synthetic-worker':{'role':'worker','pane':'synthetic-pane','reports_to':'synthetic-lead'},'synthetic-lead':{'role':'lead'}}.items():
  (root/'crew'/f'{name}.json').write_text(json.dumps(card))
 box=FilesInbox(root/'inbox')
 rows=[dict(id='fixture-a',title='first',priority=0,status='in_progress',assignee='synthetic-worker',due_at='2020-01-01T00:00:00Z'),dict(id='fixture-b',title='second',priority=1,status='open',assignee='synthetic-worker',due_at=None)]
 trk=SimpleNamespace(capacity_rows=lambda who:Answer.complete_read(rows,how='two synthetic owned seeds'))
 args=SimpleNamespace(root=root,agent='synthetic-worker',dry_run=False,reason='fixture stop',backend='files',repo=None)
 panes=NullPanes(live={'synthetic-pane'},owned={'synthetic-pane'})
 with patch.object(cli,'Tmux',return_value=panes),patch.object(cli,'_tracker',return_value=trk),patch.object(cli,'_inbox',return_value=box),patch.object(cli.harness_mod,'name_for',return_value='claude'),patch.object(cli,'_capture_history_before_kill'):
  with contextlib.redirect_stdout(io.StringIO()):
   rc=cli._cmd_stop(args)
 notices=box.unread('synthetic-lead')
 state_path=root/'owned-work'/'state.json'
 state=json.loads(state_path.read_text()) if state_path.exists() else {}
 report_path=state.get('synthetic-worker',{}).get('report')
 reported=json.loads(Path(report_path).read_text())['seeds'] if report_path else []
 print(json.dumps({'stop_exit':rc,'intent_recorded':FilesStops(root/'stopped').get('synthetic-worker') is not None,'owned_seed_positive_control':len(rows),'lead_escalations':len(notices),'both_seed_ids_in_notice':all(name in ' '.join(m.body for m in notices) for name in ['fixture-a','fixture-b']), 'ownership_unchanged':all(row['assignee']=='synthetic-worker' for row in rows), 'reported_seed_ids':[row['id'] for row in reported]}))
