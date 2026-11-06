"""Exercise the real close CLI with a controlled refusing child process."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
from subprocess import CompletedProcess
import sys
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--source', required=True)
parser.add_argument('--expect', choices=('legacy', 'fixed'), required=True)
args = parser.parse_args()
sys.path.insert(0, str(Path(args.source).resolve()))
from shantytown import cli
from shantytown.protocols import WorkItem
from shantytown.sd import SdTracker

tracker = SdTracker()
calls = []
warning = ('sd: actor/principal mismatch (observe): principal="fixture-principal" '
           + 'x' * 200 + '\n')
cause = json.dumps({'error': {'code': 'OPEN_BLOCKER', 'message': 'open blocker test-blocker'}})


def child(item_id, *command):
    calls.append(command)
    return CompletedProcess(command, 1, cause, warning)


tracker._bd_for = child
tracker.get = lambda item_id: WorkItem(item_id, status='open')
cli._tracker = lambda parsed: tracker
out, err = io.StringIO(), io.StringIO()
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory) / '.shanty'
    (root / 'crew').mkdir(parents=True)
    reason = Path(directory) / 'reason.txt'
    reason.write_text('controlled evidence')
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(['--root', str(root), 'work', 'item', 'close',
                         'test-item', '--reason-file', str(reason)])
assert code == 2 and len(calls) == 1
assert tracker.get('test-item').status == 'open'
print(err.getvalue().strip())
print('CLI exit=2; child fixture calls=1; item still open')
if args.expect == 'legacy':
    assert 'br close' in err.getvalue() and 'test-blocker' not in err.getvalue()
    print('Actual blocker hidden; sd transport reported as br')
else:
    error = json.loads(err.getvalue())['error']
    assert error['details']['backend'] == 'sd' and error['details']['exit_code'] == 1
    assert 'test-blocker' in error['details']['stdout'] and 'observe' in error['details']['stderr']
    print('Actual blocker, sd transport and child exit retained')
