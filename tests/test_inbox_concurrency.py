"""Private CAS-contending tracker controls; never calls a live SDK or pane."""
import json
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from shantytown.inbox import TrackerInbox, FilesInbox
from shantytown.protocols import WorkItem
from shantytown.sd import SdTracker


class ContendedSeeds(SdTracker):
    def __init__(self, parties=1):
        super().__init__(store='/private-fixture/never-opened', prefix='test')
        self.lock = threading.Lock()
        self.barrier = threading.Barrier(parties) if parties > 1 else None
        self.seen = set()
        self.revision = 0
        self.rows = {}
        self.keys = {}
        self.calls = []

    def get(self, item_id):
        with self.lock:
            return self.rows[item_id]

    def _bd(self, *args):
        assert args[0] == 'create', 'only private create is implemented'
        fields = dict(arg[2:].split('=', 1) for arg in args[2:] if arg.startswith('--') and '=' in arg)
        with self.lock:
            before = self.revision
            thread = threading.get_ident()
            first = thread not in self.seen
            self.seen.add(thread)
            self.calls.append(args)
        if first and self.barrier:
            self.barrier.wait(timeout=10)
        with self.lock:
            if before != self.revision:
                return subprocess.CompletedProcess(args, 4, '', 'write conflict: revision changed')
            key = (fields.get('workflow-run'), fields.get('step'), fields.get('visit'))
            if key[0] and key in self.keys:
                item = self.rows[self.keys[key]]
            else:
                item = WorkItem(id=f'test-{len(self.rows)+1}', title=args[1], status='open', assignee=fields.get('assignee'))
                self.rows[item.id] = item
                if key[0]:
                    self.keys[key] = item.id
                self.revision += 1
            return subprocess.CompletedProcess(args, 0, json.dumps({'id':item.id}), '')


def test_twelve_concurrent_recipients_get_twelve_receipts_without_duplicates():
    tracker = ContendedSeeds(12)
    box = TrackerInbox(tracker, lambda: [])
    def send(index):
        return box.deliver(f'worker{index}', 'synthetic broadcast', frm='sender')
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(send, range(12)))
    assert len({m.id for m in results}) == len(tracker.rows) == 12
    assert {m.to for m in results} == {f'worker{i}' for i in range(12)}
    print('12 concurrent CAS-contending recipients: 12 distinct receipts, no duplicates')


def test_same_key_replays_receipt_and_changed_content_refuses():
    tracker = ContendedSeeds()
    box = TrackerInbox(tracker, lambda: [])
    first = box.deliver_once('worker', 'one', 'operation', frm='sender')
    again = box.deliver_once('worker', 'one', 'operation', frm='sender')
    assert again.id == first.id and len(tracker.rows) == 1
    with pytest.raises(RuntimeError, match='receipt|identity|content'):
        box.deliver_once('worker', 'different', 'operation', frm='sender')
    assert tracker.rows[first.id].title == 'inbox: one'


@pytest.mark.parametrize('failure', [8, 1, 7, 'timeout', 'malformed'])
def test_uncertain_or_non_conflict_create_is_not_retried(failure):
    tracker = ContendedSeeds()
    calls = []
    def fail(*args):
        calls.append(args)
        if failure == 'timeout':
            raise subprocess.TimeoutExpired(args, 1)
        return subprocess.CompletedProcess(args, 0 if failure == 'malformed' else failure,
                                           'not json' if failure == 'malformed' else '', 'fixture refusal')
    tracker._bd = fail
    with pytest.raises((RuntimeError, subprocess.TimeoutExpired)):
        TrackerInbox(tracker, lambda: []).deliver('worker', 'one')
    assert len(calls) == 1


def test_cas_retries_keep_exact_native_key_and_are_bounded():
    tracker = ContendedSeeds()
    calls = []
    def conflict(*args):
        calls.append(args)
        return subprocess.CompletedProcess(args, 4, '', 'revision changed')
    tracker._bd = conflict
    with pytest.raises(RuntimeError, match='conflict'):
        TrackerInbox(tracker, lambda: []).deliver('worker', 'one')
    assert 1 < len(calls) <= 16
    assert all(args == calls[0] for args in calls)
    assert any(arg.startswith('--workflow-run=urn:shantytown:inbox:') for arg in calls[0])


def test_files_stable_delivery_is_atomic_across_threads(tmp_path):
    box = FilesInbox(tmp_path/'inbox')
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda _: box.deliver_once('worker', 'one', 'operation', frm='sender'), range(12)))
    assert len({m.id for m in results}) == 1
    assert len(box.unread('worker')) == 1
    with pytest.raises(RuntimeError, match='receipt|identity|content'):
        box.deliver_once('worker', 'different', 'operation', frm='sender')


def test_broadcast_cli_twelve_receipts_replay_and_partial_unknown(tmp_path, monkeypatch, capsys):
    from shantytown import cli
    from shantytown.protocols import Agent
    tracker = ContendedSeeds()
    box = TrackerInbox(tracker, lambda: [])
    monkeypatch.setattr(cli, '_inbox', lambda *a, **k: box)
    monkeypatch.setattr(cli, '_panes', lambda *a: object())
    monkeypatch.setattr(cli, '_verified_sender', lambda *a: ('sender', True))
    monkeypatch.setattr(cli, '_message_recipient', lambda a: Agent(name=a.agent, role='worker'))
    args = ['--root', str(tmp_path), 'inbox', 'broadcast', '--delivery-key', 'test-operation', '--json']
    for i in range(12):
        args.extend(['--to', f'worker{i}'])
    args.append('private fixture only')
    for _ in range(2):
        assert cli.main(args) == 0
        result = json.loads(capsys.readouterr().out)
        assert len(result['receipts']) == 12
        assert all(r['delivery'] == 'persisted' for r in result['receipts'])
        assert result['live_nudges'] == 0
        assert len(tracker.rows) == 12
    original = box.deliver_once
    def unknown(to, *a, **k):
        if to == 'worker3':
            raise subprocess.TimeoutExpired('synthetic SDK', 1)
        return original(to, *a, **k)
    monkeypatch.setattr(box, 'deliver_once', unknown)
    assert cli.main(args) == 2
    result = json.loads(capsys.readouterr().out)
    assert sum(r['delivery'] == 'UNKNOWN' for r in result['receipts']) == 1
    assert sum(r['delivery'] == 'persisted' for r in result['receipts']) == 11
    assert len(tracker.rows) == 12


def test_broadcast_unknown_recipient_preflight_writes_nothing(tmp_path, monkeypatch, capsys):
    from shantytown import cli
    monkeypatch.setattr(cli, '_panes', lambda *a: object())
    monkeypatch.setattr(cli, '_verified_sender', lambda *a: ('sender', True))
    monkeypatch.setattr(cli, '_message_recipient', lambda a: (_ for _ in ()).throw(LookupError('unknown recipient')))
    monkeypatch.setattr(cli, '_inbox', lambda *a, **k: pytest.fail('backend reached before complete preflight'))
    assert cli.main(['--root',str(tmp_path),'inbox','broadcast','--to','missing','--delivery-key','operation','hello']) == 1


@pytest.mark.real_store
def test_native_seeds_keyed_receipt_replay_after_ack_and_collision(tmp_path):
    import shutil
    binary = shutil.which('sd')
    if binary is None:
        pytest.skip('native sd is unavailable')
    project = tmp_path/'project'
    project.mkdir()
    store = tmp_path/'board.db'
    subprocess.run([binary, 'init', '--prefix', 'test'], cwd=project, check=True, capture_output=True, text=True)
    subprocess.run([binary, '--store', str(store), 'create', 'private bootstrap'], cwd=project,
                   check=True, capture_output=True, text=True)
    tracker = SdTracker(repo=str(project), store=str(store), prefix='test')
    box = TrackerInbox(tracker, lambda: [])
    with ThreadPoolExecutor(max_workers=12) as pool:
        messages = list(pool.map(lambda i: box.deliver_once(
            f'worker{i}', 'native private concurrency', 'native-broadcast', frm='sender'), range(12)))
    assert len({m.id for m in messages}) == 12
    for i, message in enumerate(messages):
        again = box.deliver_once(f'worker{i}', 'native private concurrency', 'native-broadcast', frm='sender')
        assert again.id == message.id
    first = box.deliver_once('worker', 'native private fixture', 'native-operation', frm='sender')
    tracker.update(first.id, status='closed')
    second = box.deliver_once('worker', 'native private fixture', 'native-operation', frm='sender')
    assert second.id == first.id and second.read
    with pytest.raises(RuntimeError, match='receipt|identity|content'):
        box.deliver_once('worker', 'changed', 'native-operation', frm='sender')
    assert tracker.get(first.id).title == 'inbox: native private fixture'


def test_receipt_readback_timeout_after_committed_create_never_resends():
    tracker = ContendedSeeds()
    def lost_read(item_id):
        raise subprocess.TimeoutExpired('private readback', 1)
    tracker.get = lost_read
    with pytest.raises(subprocess.TimeoutExpired):
        TrackerInbox(tracker, lambda: []).deliver('worker', 'one')
    assert len(tracker.rows) == len(tracker.calls) == 1


def test_same_key_distinct_recipients_have_independent_receipts():
    tracker = ContendedSeeds()
    box = TrackerInbox(tracker, lambda: [])
    one = box.deliver_once('one', 'body', 'operation', frm='sender')
    two = box.deliver_once('two', 'body', 'operation', frm='sender')
    assert one.id != two.id and len(tracker.rows) == 2


def test_retained_pointer_slug_reaches_native_inbox_create():
    tracker = ContendedSeeds()
    slug = 'rr' + '1' * 24
    message = TrackerInbox(tracker, lambda: []).deliver(
        'worker', 'retained pointer', frm='sender', slug=slug)
    assert message.id in tracker.rows
    assert len(tracker.calls) == 1
    assert f'--slug={slug}' in tracker.calls[0]
    assert '--assignee=worker' in tracker.calls[0]
    assert '--labels=inbox' in tracker.calls[0]


@pytest.mark.parametrize('extra', [
    {'priority': 0}, {'status': 'closed'}, {'defer_until': 'tomorrow'},
])
def test_native_inbox_create_still_refuses_non_message_fields(extra):
    tracker = ContendedSeeds()
    with pytest.raises(ValueError, match='only message identity fields'):
        tracker.create_inbox_message(
            'inbox: retained pointer', delivery_key='operation',
            assignee='worker', labels='inbox', slug='rr' + '1' * 24, **extra)
    assert tracker.calls == []


def test_files_unkeyed_concurrent_delivery_preserves_every_message(tmp_path):
    box = FilesInbox(tmp_path/'inbox')
    with ThreadPoolExecutor(max_workers=12) as pool:
        messages = list(pool.map(lambda i: box.deliver('worker', f'message {i}'), range(12)))
    assert len({m.id for m in messages}) == 12
    assert {m.body for m in box.unread('worker')} == {f'message {i}' for i in range(12)}


def test_broadcast_dry_run_never_opens_backend(tmp_path, monkeypatch, capsys):
    from shantytown import cli
    from shantytown.protocols import Agent
    monkeypatch.setattr(cli, '_panes', lambda *a: object())
    monkeypatch.setattr(cli, '_verified_sender', lambda *a: ('sender', True))
    monkeypatch.setattr(cli, '_message_recipient', lambda a: Agent(name=a.agent, role='worker'))
    monkeypatch.setattr(cli, '_inbox', lambda *a, **k: pytest.fail('dry run opened backend'))
    assert cli.main(['--root',str(tmp_path),'inbox','broadcast','--to','worker',
                     '--delivery-key','operation','--dry-run','hello']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['writes'] == result['live_nudges'] == 0
