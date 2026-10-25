"""Record actual CLI output against local role fixtures; no graph/network calls."""
import contextlib
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def child(checkout):
    sys.path.insert(0,str(Path(checkout).resolve()))
    from shantytown import cli
    from shantytown.tmux import NullPanes
    ns='https://crew.example/roles/'
    try:
        from shantytown import crew_rules
        def ask(root,query,params,**kwargs):
            roles=['administrator','lead','keeper','worker','reviewer'] if params['role']=='*' else [params['role'].removeprefix(ns)]
            return [{'rule':ns+r+'-duty','scope':ns+r,'topic':'responsibilities',
                     'summary':r+' duty from the graph fixture','text':'full fixture responsibility'} for r in roles]
        crew_rules.ask=ask
    except ImportError:
        pass  # The base has no responsibility reader.
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);(root/'crew').mkdir()
        (root/'shantytown.toml').write_text('[env]\nSHANTY_RULES_QUERY="fixture_rules"\nSHANTY_ONTO_NS="'+ns+'"\n')
        for name,role,lead in [('chief','administrator',None),('team','lead','chief'),('member','worker','team')]:
            (root/'crew'/f'{name}.json').write_text(json.dumps({'role':role,'reports_to':lead,'pane':name}))
        cli._panes=lambda a:NullPanes(live={'chief','team','member'})
        cli._lead_status=lambda *a:lambda name:True
        for command in [['anchor','member'],['fleet','roles','show']]:
            print('$ st '+' '.join(command))
            output=io.StringIO()
            with contextlib.redirect_stdout(output):
                code=cli.main(['--root',str(root),'--backend','files',*command])
            assert code==0
            print(output.getvalue().strip())


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--child':child(sys.argv[2])
    else:
        if len(sys.argv)!=2:raise SystemExit('usage: reproduce.py BEFORE_CHECKOUT')
        after=Path(__file__).resolve().parents[3]
        for label,checkout in [('before',Path(sys.argv[1])),('after',after)]:
            print('\n'+label+': actual CLI, isolated files and graph-response fixtures',flush=True)
            subprocess.run([sys.executable,__file__,'--child',str(checkout)],check=True)
