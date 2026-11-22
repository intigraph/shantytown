"""Actual SDK adapter with isolated in-memory board transport; no live calls."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace

BASE = '6c115c7fa034d46965201f98219ef7627e5cef4b'
ROOT = Path(__file__).resolve().parents[4]


def probe(root):
    sys.path.insert(0, root)
    from shantytown.sd import SdTracker
    payload = dict(id='queue', holder='worker', kind='merge-queue')
    key = 'stranded-duty:' + hashlib.sha256(b'queue').hexdigest()
    row = dict(id='work-1', title='P0 orphaned duty: queue',
               description=key + '\n' + json.dumps(payload, sort_keys=True),
               assignee='lead', labels=['orphaned-duty'], status='open',
               priority=0, revision=7)
    calls = []
    tracker = SdTracker.__new__(SdTracker)

    def create(*args):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout='{"id":"work-1"}')

    def close(identifier, *args):
        assert identifier == 'work-1' and '--if-revision=7' in args
        calls.append(args)
        row['status'] = 'closed'
        return SimpleNamespace(returncode=0)

    tracker._bd, tracker._bd_for = create, close
    tracker.get = lambda _: SimpleNamespace(**row)
    tracker.stranded_read = lambda _: dict(row)
    tracker.create_duty_issue(payload, target='lead', key=key)
    record_type = next((x.split('=', 1)[1] for x in calls[0]
                        if x.startswith('--type=')), 'task (default)')
    resolver = getattr(tracker, 'resolve_duty_issue', None)
    if resolver:
        try:
            resolver(payload, 'work-1', target='other', evidence='live holder')
        except ValueError:
            assert len(calls) == 1
        else:
            raise AssertionError('foreign target accepted')
        assert resolver(payload, 'work-1', target='lead', evidence='fresh live holder')
    print(json.dumps(dict(created_type=record_type,
                          after_verified_recovery=row['status'],
                          foreign_target='refused without write' if resolver else 'no resolver')))


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--probe':
        probe(sys.argv[2])
    else:
        print('Synthetic board; production adapter; no resident commands.', flush=True)
        with tempfile.TemporaryDirectory() as directory:
            archive = subprocess.check_output(['git', 'archive', BASE, 'shantytown'], cwd=ROOT)
            with tarfile.open(fileobj=io.BytesIO(archive)) as source:
                source.extractall(directory, filter='data')
            for label, root in [('BASE ' + BASE, directory),
                                ('CANDIDATE ' + subprocess.check_output(
                                    ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(), str(ROOT))]:
                print(label, flush=True)
                subprocess.run([sys.executable, __file__, '--probe', root], check=True)
