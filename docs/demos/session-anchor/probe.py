import contextlib,io,json,os,subprocess,types
from unittest.mock import patch
for label, revision in [('before', 'a8b6584'), ('after', 'HEAD')]:
 source=subprocess.check_output(['git','show',revision+':shantytown/session_anchor.py'],text=True)
 mod=types.ModuleType('shantytown.fixture_anchor');mod.__package__='shantytown'
 exec(compile(source,'session_anchor.py','exec'),mod.__dict__)
 with patch.dict(os.environ,{'SHANTY_AGENT':'fixture','SHANTY_ROOT':'/fixture'}),patch.object(mod,'_run_anchor',return_value=(0,'ON YOUR PLATE\n    x-1  do the thing\n')),patch('sys.stdin',io.StringIO('{}')):
  out=io.StringIO()
  with contextlib.redirect_stdout(out):mod.main([])
  payload=json.loads(out.getvalue());ctx=payload['hookSpecificOutput']['additionalContext']
  print(label,json.dumps({'terminal_lines':len(payload.get('systemMessage','').splitlines()),'context_lines':len(ctx.splitlines()),'context_retained':ctx==mod.render('/fixture','fixture')}))
