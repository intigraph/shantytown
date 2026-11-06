"""Private local files only: no tracker, harness process, network, or live tend."""
import hashlib
import json
from pathlib import Path
import tempfile
import time

from shantytown.refill import Refiller, metrics
from shantytown.refill_reconcile import reconcile


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    now = int(time.time())
    worker, item, session = 'worker', 'work-1', 'session-id'
    custody_id = 'send-' + 'b' * 32
    body = 'Work is on your hook: work-1 — private task — [st serve:' + 'a' * 32 + ' worker:worker]'
    put(root / 'crew/worker.json', dict(pane='worker-pane', workspace=directory, harness='codex'))
    put(root / 'refill/state.json', dict(pending={worker: dict(item=item, at=now - 30)},
        observed_at=now - 20, coverage=True, observations={}, observation_error='PartialAnswer'))
    (root / 'refill/lock').touch()
    put(root / 'delivery' / (custody_id + '.json'), dict(id=custody_id, pane='worker-pane',
        socket='fixture', text=body, created=now - 25, session=now - 100, state='unknown'))
    history = root / 'history/worker/rollout-session-id.jsonl'
    def utc(seconds):
        return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(seconds))
    meta = dict(type='session_meta', timestamp=utc(now - 100), payload=dict(id=session, cwd=directory))
    event = dict(type='response_item', timestamp=utc(now - 10), payload=dict(type='message',
        role='user', content=[dict(type='input_text', text=body)]))
    raw = json.dumps(event) + '\n'
    history.parent.mkdir(parents=True)
    history.write_text(json.dumps(meta) + '\n' + raw)
    request = dict(version=1, worker=worker, item=item, pending_at=now - 30,
        custody=custody_id, history=history.name, line=2, event_sha256=hashlib.sha256(raw.encode()).hexdigest())
    def values():
        return {line.split()[0]: float(line.split()[1]) for line in metrics(root, now).splitlines()}
    print('Target: private source fixture; existing uncertain dispatch, not installed acceptance')
    print('before: pending=', int(values()['st_refill_pending_dispatches']),
          'known=', int(values()['st_refill_observation_known']))
    assert reconcile(root, request)['state'] == 'qualified'
    print('read-only qualification: exact native user receipt accepted, reservation retained')
    try:
        reconcile(root, dict(request, event_sha256='0' * 64), apply=True)
    except ValueError:
        print('wrong receipt: REFUSED; pending still', int(values()['st_refill_pending_dispatches']))
    else:
        raise AssertionError('wrong receipt was accepted')
    assert reconcile(root, request, apply=True)['state'] == 'reconciled'
    print('after: pending=', int(values()['st_refill_pending_dispatches']),
          'known=', int(values()['st_refill_observation_known']), '(original PartialAnswer preserved)')
    assert reconcile(root, request, apply=True)['state'] == 'already-reconciled'
    print('same receipt again: already-reconciled; no dispatch or second audit transition')
    def no_send(*args):
        raise AssertionError('no send is permitted in this demonstration')
    Refiller(root, None, None, None, snapshot=lambda: ([], []), preview=no_send,
        dispatch=no_send, free=lambda: [], log=lambda *a: None, clock=lambda: now).sweep()
    print('separate private ordinary-observation fixture: known=', int(values()['st_refill_observation_known']))
    print('No production state, schedule, message, or harness was changed.')
