"""Compare actual initial dispatch/native reader composition in isolated fixtures."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def child(source, kind):
    sys.path.insert(0, source)
    import pytest
    from shantytown.dispatch import SendUnverified
    from shantytown.dispatch_receipts import ReceiptConflict
    path = Path(__file__).resolve().parents[3] / 'tests/test_dispatch_initial_native_submission.py'
    spec = importlib.util.spec_from_file_location('initial_native_fixture', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory() as directory, pytest.MonkeyPatch.context() as patch:
        d, binding, tracker, panes, state, keys = module.world.__wrapped__(Path(directory), patch)
        state['kind'] = kind
        try:
            plan = d.go('work-1', 'worker')
        except (SendUnverified, ReceiptConflict):
            row = binding.store.pending('work-1')
        else:
            row = binding.store.read(plan.receipt_id)
        result = dict(case=kind, receipt=row['state'],
                      submission=row['submission'] is not None,
                      assignment=row['assignment'] is not None,
                      revision=tracker.get('work-1').revision,
                      authorized=binding.reconcile(row['id'])['execution_authorized'],
                      sends=len(panes.sent), enters=sum(k[-1] == 'Enter' for k in keys))
        print(json.dumps(result, sort_keys=True))


def main():
    if len(sys.argv) == 4 and sys.argv[1] == '--child':
        child(sys.argv[2], sys.argv[3])
        return
    for phase, key in [('before', 'NATIVE_DEMO_BASELINE'), ('after', 'NATIVE_DEMO_CANDIDATE')]:
        for kind in ['user', 'queue', 'runtime']:
            run = subprocess.run([sys.executable, __file__, '--child', os.environ[key], kind],
                                 check=True, capture_output=True, text=True)
            row = json.loads(run.stdout)
            positive = phase == 'after' and kind == 'user'
            assert row['authorized'] == row['submission'] == row['assignment'] == positive
            assert row['sends'] == row['enters'] == 1
            assert row['revision'] == (2 if positive else 1)
            print(phase + ': ' + json.dumps(row, sort_keys=True))
    print('PASS: exact native consumption authorizes one initial claim; queue-only and runtime changes remain fenced.')


if __name__ == '__main__':
    main()
