"""Run against either base or candidate using PYTHONPATH; private native Seeds."""
import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory

from shantytown.br import items
from shantytown.inbox import TrackerInbox
from shantytown.sd import br_like_tracker

BOARD='https://tracker.example/board'
INBOX=BOARD+'/inbox'


def main():
    binary=shutil.which('sd')
    if binary is None:
        raise SystemExit('native sd is required')
    with TemporaryDirectory(prefix='inbox-demo-') as directory:
        root=Path(directory)
        os.environ.update(HOME=str(root),XDG_CONFIG_HOME=str(root/'config'),
                          XDG_STATE_HOME=str(root/'state'))
        for key in list(os.environ):
            if key.startswith(('SEEDS_','SHANTY_','QUIPU_','ST_','AEGIS_TRACKER_')):
                os.environ.pop(key)
        project=root/'project';project.mkdir()
        database=root/'private.db'
        def sdk(graph,*args):
            result=subprocess.run([binary,'--store',str(database),'--graph',graph,*args],
                    cwd=project,text=True,capture_output=True,check=True,timeout=30)
            return json.loads(result.stdout)
        subprocess.run([binary,'init','--prefix','work'],cwd=project,
                       capture_output=True,text=True,check=True,timeout=30)
        (project/'.seeds/config.toml').write_text(
            '[project]\nprefix="work"\ngraph="'+BOARD+'"\n')
        work=sdk(BOARD,'create','real work control','--json')
        old=sdk(INBOX,'create','inbox: [receipt:legacy] retained',
                '-a','worker','-l','inbox','--json')
        values={'SHANTY_BACKEND':'seeds','SHANTY_SD_STORE':str(database),
                'SHANTY_SD_PREFIX':'work','SHANTY_SD_INBOX_GRAPH':INBOX,
                'SHANTY_SD_INBOX_PREFIX':'messages'}
        tracker=br_like_tracker(values.get);tracker.repo=str(project)
        scope=getattr(tracker,'inbox_tracker',lambda:tracker)()
        box=TrackerInbox(scope,lambda:items(scope),
                         items_for=getattr(scope,'inbox_items',None))
        found=box.find_delivery('worker','[receipt:legacy]')
        new=box.deliver('worker','[receipt:new] retained')
        board=sdk(BOARD,'list','--limit','5','--json')
        rows=board.get('issues',board) if isinstance(board,dict) else board
        print('same input: board has one work item; inbox has a legacy receipt')
        print('legacy receipt found:',found is not None)
        print('new ID uses messages prefix:',new.id.startswith('messages-'))
        print('inbox pointers leaked onto work board:',sum(r['title'].startswith('inbox:') for r in rows))
        assert any(r['id']==work['id'] and r['status']=='open' for r in rows)
        print('real work remains open:',True)
        if found is not None:
            box.mark_read('worker',[old['id']])
            assert box.find_delivery('worker','[receipt:legacy]').read
            print('closed legacy receipt remains discoverable:',True)
        print('production requests:',0)


if __name__=='__main__':
    main()
