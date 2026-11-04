"""Source-library demonstration; all tracker and inbox adapters are fixtures."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from shantytown.answer import Answer
from shantytown.unlock_reader import UnlockReader, react

BASE='00aeb887d5ec2f8575283bd1c8eca5bbf09aa795'

class Registry:
    def get(self,name):return SimpleNamespace(name=name)

with tempfile.TemporaryDirectory() as directory:
    root=Path(directory)
    baseline=root/'baseline.py'
    baseline.write_bytes(subprocess.check_output(['git','show',BASE+':shantytown/unlock_reader.py']))
    spec=importlib.util.spec_from_file_location('shantytown.baseline_reader',baseline)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    try:
        module.UnlockReader(None,root,identifier='example-1')
    except TypeError as error:
        assert 'identifier' in str(error)
        print('BEFORE: targeted reader rejected the identifier keyword')
    else:
        raise AssertionError('baseline unexpectedly supports targeted reader')
    calls=[];stored=[None];acks=[]
    event=dict(kind='unlock',id='example-1',episode='seeds:unlock:example-1:1',recipient='worker')
    def reconcile(identifier):
        assert identifier=='example-1'
        calls.append(('reconcile',identifier))
    def events(identifier):
        assert identifier=='example-1'
        return Answer.complete_read([event],how='isolated fixture')
    def ack(*args):
        acks.append(args);stored[0]=args[2]
        raise TimeoutError('fixture lost ACK response after commit')
    tracker=SimpleNamespace(reconcile_blockers=reconcile,unlock_events=events,
        unlock_receipt=lambda *args:stored[0],ack_unlock=ack)
    sends=[]
    def deliver(*args):sends.append(args);return 'fixture-receipt-1'
    kwargs=dict(deliver=deliver,receipt=lambda *args:None)
    assert react(tracker,root,Registry(),'example-1',**kwargs)==['worker']
    assert react(tracker,root,Registry(),'example-1',**kwargs)==[]
    assert len(sends)==1 and len(acks)==1
    print('AFTER: native calls target example-1; shared notifier fixture sends',len(sends),'message')
    print('LOST ACK RESPONSE + REPLAY: no resend;',len(acks),'ACK write; retained receipt confirmed')
    ledger=json.loads((root/'notify'/'overdue.json').read_text())
    assert all(value['ack']=='confirmed' for value in ledger['entries'].values())
    print('LIMIT: source/fixture behavior only; no installed reaction or live delivery')
