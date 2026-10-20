"""Private library fixture: acknowledge a named receipt, never a live inbox."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from shantytown import cli  # noqa: E402
from shantytown.answer import Answer  # noqa: E402
from shantytown.inbox import TrackerInbox  # noqa: E402
from shantytown.protocols import WorkItem  # noqa: E402

BASE = 'd8902bcdf3b6c5e83de01603bc84cc25873b5462'
source = subprocess.check_output(['git', '-C', str(ROOT), 'show', BASE+':shantytown/cli.py']).decode()
node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == '_inbox_read')
namespace = dict(vars(cli))
exec(compile(ast.Module(body=[node], type_ignores=[]), '<base inbox reader>', 'exec'), namespace)


def probe(label, function, globals_):
    calls = []
    receipt = WorkItem('demo-receipt', 'inbox: private example', 'open', 'reader')
    class Tracker:
        def get(self, identifier):
            calls.append('get')
            assert identifier == receipt.id
            return receipt
        def update(self, identifier, **fields):
            assert identifier == receipt.id and fields == {'status': 'closed'}
            calls.append('close')
    def listing(*args):
        calls.append('enumerate')
        return Answer.complete_read([receipt], how='private fixture')
    box = TrackerInbox(Tracker(), lambda: [receipt], items_for=listing)
    globals_['_inbox'] = lambda *a, **kw: box
    args = argparse.Namespace(count=False, read=False, read_id=[receipt.id], dry_run=False)
    assert function(args, 'reader') == cli.OK
    result = {name: calls.count(name) for name in ('enumerate', 'get', 'close')}
    print(label, json.dumps(result, sort_keys=True))
    assert result == {'enumerate': int(label == 'before'),
                      'get': 1 if label == 'before' else 2, 'close': 1}


print('Base function:', BASE)
probe('before', namespace['_inbox_read'], namespace)
probe('after', cli._inbox_read, vars(cli))
for name in ('cli.py', 'inbox.py'):
    print(name, 'SHA256:', hashlib.sha256((ROOT/'shantytown'/name).read_bytes()).hexdigest())
