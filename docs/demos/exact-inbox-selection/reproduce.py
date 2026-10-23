"""Private library fixture: acknowledge a named receipt, never a live inbox."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import types

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from shantytown import cli  # noqa: E402
from shantytown.answer import Answer  # noqa: E402
from shantytown.inbox import TrackerInbox  # noqa: E402
from shantytown.protocols import WorkItem  # noqa: E402

BASE = 'e834ef6395e0b4edae094f29515177006d5f5ba5'
source = subprocess.check_output(['git', '-C', str(ROOT), 'show', BASE+':shantytown/inbox.py']).decode()
klass = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == 'TrackerInbox')
node = next(n for n in klass.body if isinstance(n, ast.FunctionDef) and n.name == 'unread_selected')
from shantytown import inbox  # noqa: E402
namespace = dict(vars(inbox))
exec(compile(ast.Module(body=[node], type_ignores=[]), '<original named selector>', 'exec'), namespace)


def probe(label):
    calls = []
    receipt = WorkItem('demo-receipt', 'inbox: private example', 'open', 'reader')
    class Tracker:
        def get(self, identifier):
            calls.append('get')
            assert identifier == receipt.id
            return receipt
        def inbox_receipts(self, me, identifiers):
            assert me == receipt.assignee and identifiers == [receipt.id]
            calls.append('receipt')
            return Answer.complete_read([receipt], how='private exact metadata')
        def update(self, identifier, **fields):
            assert identifier == receipt.id and fields == {'status': 'closed'}
            calls.append('close')
    def listing(*args):
        calls.append('enumerate')
        return Answer.complete_read([receipt], how='private fixture')
    box = TrackerInbox(Tracker(), lambda: [receipt], items_for=listing)
    if label == 'before':
        box.unread_selected = types.MethodType(namespace['unread_selected'], box)
    cli._inbox = lambda *a, **kw: box
    args = argparse.Namespace(count=False, read=False, read_id=[receipt.id], dry_run=False)
    assert cli._inbox_read(args, 'reader') == cli.OK
    result = {name: calls.count(name) for name in ('enumerate', 'get', 'receipt', 'close')}
    print(label, json.dumps(result, sort_keys=True))
    assert result == {'enumerate': 0, 'get': int(label == 'before'),
                      'receipt': 1 if label == 'before' else 2, 'close': 1}


print('Base function:', BASE)
probe('before')
probe('after')
for name in ('cli.py', 'inbox.py'):
    print(name, 'SHA256:', hashlib.sha256((ROOT/'shantytown'/name).read_bytes()).hexdigest())
