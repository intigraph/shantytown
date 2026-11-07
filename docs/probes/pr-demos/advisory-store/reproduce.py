"""Compare real advisory functions with intercepted transport/store/model fixtures."""
import io
import json
from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from shantytown import create_advisory as current

BASE = 'ee7bf0a2265319967c2a042b149703d8b6346706'
source = subprocess.check_output(['git','show',BASE+':shantytown/create_advisory.py'],cwd=ROOT,text=True)
previous = ModuleType('shantytown.advisory_before'); previous.__package__ = 'shantytown'
exec(compile(source, 'advisory_before.py', 'exec'), previous.__dict__)

class Jev:
    def __init__(self,*args,**kwargs): pass
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def call(self,tool,arguments):
        return dict(request=arguments,model='fixture',usage={},answer=dict(noul=.95))

request = dict(title='repair leak',tracker=dict(backend='seeds',quipu='http://board.invalid',prefix='test'))
for label,module in [('base',previous),('candidate',current)]:
    calls=[]
    def store(argv,**kwargs):
        calls.append(argv[0])
        if argv[0]=='fixture-br':
            return SimpleNamespace(returncode=1,stdout='',stderr='fixture legacy store has no exact item')
        assert argv[0]=='fixture-sd'
        if 'where' in argv:
            data=dict(location_source='--quipu',quipu_url='http://board.invalid',prefix='test',graph='urn:test:board')
        else:
            assert argv[-3:]==['show','test-42','--json']
            data=dict(id='test-42',title='repair leak',description='',status='open')
        return SimpleNamespace(returncode=0,stdout=json.dumps(data),stderr='')
    with patch.dict('os.environ',BOBBIN_SERVER='http://search.invalid',SHANTY_CREATE_JEV_COMMAND='fixture-jev',
                    SHANTY_BR_BIN='fixture-br',SHANTY_SD_BIN='fixture-sd'), \
         patch.object(module.urllib.request,'urlopen',lambda *a,**k:io.StringIO(json.dumps(dict(count=1,results=[dict(bead_id='test-42')])))), \
         patch.object(module.subprocess,'run',store),patch.object(module,'JevMCP',Jev):
        try: outcome=module.evaluate(request)['outcome']
        except module.TriageError as error: outcome='skipped: '+str(error)
        print(label+': '+outcome+'; store calls='+','.join(calls))
        if label=='base': assert outcome.startswith('skipped') and calls==['fixture-br']
        else: assert outcome=='fired' and calls==['fixture-sd','fixture-sd']
print('Fixture only: no network, tracker mutation, real model or installed-service claim.')
