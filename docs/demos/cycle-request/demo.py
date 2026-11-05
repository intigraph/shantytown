import argparse,ast,contextlib,io,json,subprocess,tempfile,sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from shantytown import cli,br,cycle,help_topics
source=subprocess.check_output(['git','show','bccb036:shantytown/cli.py'],text=True)
node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='_cmd_cycle')
ns=dict(cli.__dict__);exec(compile(ast.Module(body=[node],type_ignores=[]),'<base>','exec'),ns)
base=ns['_cmd_cycle']
for label,fn in [('BEFORE bccb036',base),('AFTER candidate',cli._cmd_cycle)]:
 with tempfile.TemporaryDirectory() as d,contextlib.ExitStack() as stack:
  root=Path(d);notes=root/'notes';notes.write_text('Next: check accepted head\nLanded: A\nLocal: none\nDecisions: preserve holds')
  reads=[];posts=[];quality=[]
  def durable(*a):reads.append('plate/comments');return SimpleNamespace(checkpoint='previous comment',since='launch')
  patches=[patch.object(cli,'_registry',return_value=SimpleNamespace(get=lambda _:SimpleNamespace(role='worker',name='fixture',pane='fixture'))),patch.object(cli,'_cycle_stop_refusal',return_value=''),patch.object(cli,'_tracker',return_value=SimpleNamespace(get=lambda _:{})),patch.object(cli,'_backend',return_value='seeds'),patch.object(cli,'_graph_context',return_value=(SimpleNamespace(nodes=['fixture-node'],exemption=''),'')),patch.object(cli.graph_adoption,'record'),patch.object(br,'append_comment',side_effect=lambda t,b,c:posts.append(c)),patch.object(cli,'_durable_checkpoint_gate',side_effect=durable),patch.object(cli,'_checkpoint_quality_gate',side_effect=lambda a,w,text,s:quality.append(text) or (True,'')),patch.object(cli,'_spawn_self_cycle_server',return_value='')]
  for p in patches:stack.enter_context(p)
  if fn is base:
   for name in ['_registry','_cycle_stop_refusal','_tracker','_backend','_graph_context','_durable_checkpoint_gate','_checkpoint_quality_gate','_spawn_self_cycle_server']:base.__globals__[name]=getattr(cli,name)
  args=argparse.Namespace(root=root,agent='fixture',self_=True,reason='',checkpoint_file=str(notes),checkpoint_bead='task',dry_run=False,no_in_place=False,quipu_node=['fixture-node'],no_graph_context='',allow_loss=False,despite_hold='',serve_request=False)
  with contextlib.redirect_stdout(io.StringIO()):rc=fn(args)
  print(label,json.dumps(dict(exit=rc,checkpoint_posts=len(posts),quality_tracker_reads=len(reads),quality_uses_supplied_file=quality==[notes.read_text()],request_recorded='fixture' in cycle.Requests(root).pending())))
  assert rc==0 and len(posts)==1
  if fn is not base:assert not reads and quality==[notes.read_text()]
print('Scope: isolated request fixture, no waiter or host action; execution guards are unchanged.')

help_ns={'__name__':'shantytown.demo_old_help','__package__':'shantytown'}
old_help=subprocess.check_output(['git','show','bccb036:shantytown/help_topics.py'],text=True)
exec(compile(old_help,'<base-help>','exec'),help_ns)
for label,text in [('BEFORE help',help_ns['render']('handoff')),('AFTER help',help_topics.render('handoff'))]:
    print(label,json.dumps(dict(tells_agent_keep_working='keep working until it fires' in text,
                               fixed_template='CHECKPOINT TEMPLATE' in text,
                               end_turn='END YOUR TURN' in text)))
assert 'keep working until it fires' not in help_topics.render('handoff')
