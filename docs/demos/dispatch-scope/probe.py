"""Disposable receipt fixture; never connects to a board or a terminal pane."""
import json
from pathlib import Path
import tempfile

from shantytown.dispatch_receipts import ReceiptConflict, ReceiptStore


with tempfile.TemporaryDirectory() as directory:
    store = ReceiptStore(Path(directory))
    scope = dict(item='work-1', revision=4, worker='ada', pane='%5', session=123,
                 task_sha256='fixture-task', scope_sha256='fixture-scope')
    row, fresh = store.prepare(scope, 'fixture work', ident='1' * 32)
    assert fresh
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns)
              for p in store.root.iterdir() if p.is_file()}
    print('Fixture: retained prepared receipt for ada; request the same item for ben.')
    try:
        store.prepare(dict(scope, worker='ben', revision=5), 'new fixture work')
    except ReceiptConflict as error:
        print('REFUSED:', error)
    else:
        raise AssertionError('changed scope must remain refused')
    after = {p.name: (p.read_bytes(), p.stat().st_mtime_ns)
             for p in store.root.iterdir() if p.is_file()}
    assert before == after
    status = store.status(row['id'], scope)
    assert status['state'] == 'prepared' and not status['execution_authorized']
    print('Read-only status:', json.dumps(status, sort_keys=True))
    print('PASS: retained bytes/mtimes unchanged; no send, claim or supersession.')
