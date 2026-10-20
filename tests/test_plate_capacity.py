"""A cap is proved at the mutation boundary, including real concurrent CLIs."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from shantytown import cli
from shantytown.answer import Answer
from shantytown.dispatch import Dispatcher
from shantytown.files import FilesRegistry, FilesTracker
from shantytown.plate_capacity import CapacityUnknown, PlateFull, ensure_room, size
from shantytown.sd import SdTracker
from shantytown.tmux import NullPanes


def world(tmp_path, count=10):
    root = tmp_path / 'world'
    (root / 'crew').mkdir(parents=True)
    (root / 'crew' / 'worker.json').write_text(json.dumps({'pane': '%1'}))
    tracker = FilesTracker(root / 'items')
    for i in range(count):
        tracker.create(f'Work {i}', assignee='worker')
    return root, tracker


@pytest.mark.parametrize('dry_run', [False, True])
def test_go_full_has_no_send_or_write(tmp_path, dry_run):
    root, tracker = world(tmp_path)
    pool = tracker.create('Pool item')
    panes = NullPanes()
    dispatcher = Dispatcher(FilesRegistry(root / 'crew'), tracker, panes)
    before = tracker._path(pool.id).read_bytes()
    with pytest.raises(PlateFull):
        dispatcher.go(pool.id, 'worker', dry_run=dry_run)
    assert tracker._path(pool.id).read_bytes() == before
    assert panes.sent == []


def test_ninth_can_become_tenth_and_same_owner_resume_at_ten(tmp_path):
    root, tracker = world(tmp_path, 9)
    pool = tracker.create('Tenth item')
    dispatcher = Dispatcher(FilesRegistry(root / 'crew'), tracker, NullPanes())
    dispatcher.go(pool.id, 'worker')
    assert size(tracker, 'worker') == 10
    dispatcher.go(pool.id, 'worker', dry_run=True)
    assert size(tracker, 'worker') == 10


def test_full_task_preserves_work_unassigned_and_dry_run_creates_nothing(tmp_path):
    root, tracker = world(tmp_path)
    assert cli.main(['--root', str(root), 'task', '-a', 'worker', 'Overflow']) == cli.REFUSED
    assert size(tracker, 'worker') == 10
    assert tracker.get('st-11').assignee is None
    assert cli.main(['--root', str(root), 'task', '-a', 'worker', '-n', 'Dry']) == cli.REFUSED
    assert not tracker._path('st-12').exists()


def test_messages_deferred_terminal_records_and_other_owner_do_not_use_slots(tmp_path):
    root, tracker = world(tmp_path, 0)
    for status in ('open', 'hooked', 'in_progress', 'blocked'):
        tracker.create(status, assignee='rig/worker', status=status)
        # create fixes open in its returned WorkItem; persisted status is the control.
    for status in ('deferred', 'closed', 'tombstone'):
        tracker.create(status, assignee='worker', status=status)
    tracker.create('inbox: note', assignee='worker')
    tracker.create('Permanent', assignee='worker', labels=['anchor'])
    tracker.create('Handoff', assignee='worker', labels=['handoff'])
    tracker.create('Later', assignee='worker', defer_until='2099-01-01T00:00:00Z')
    tracker.create('Past', assignee='worker', defer_until='2000-01-01T00:00:00Z')
    tracker.create('Another owner', assignee='other')
    assert size(tracker, 'worker') == 5


def test_incomplete_owner_snapshot_never_authorizes_assignment():
    class Partial:
        def capacity_rows(self, owner):
            return Answer.capped([], how='owner scope', caveat='truncated')
    with pytest.raises(CapacityUnknown, match='truncated'):
        ensure_room(Partial(), 'worker')


def test_seeds_capacity_does_not_stop_at_held_rank(monkeypatch):
    tracker = SdTracker(quipu='https://example.test', prefix='fixture')
    monkeypatch.setattr(tracker, '_use_remote_projection', lambda: False)
    calls = []
    def run(*args):
        calls.append(args)
        assert '--assignee' in args and '--status' not in args
        rows = [dict(id=str(i), title='Work', assignee='worker', status='open') for i in range(10)]
        return subprocess.CompletedProcess(args, 0, json.dumps({'issues': rows, 'total': 10, 'has_more': False}), '')
    monkeypatch.setattr(tracker, '_bd', run)
    with pytest.raises(PlateFull):
        ensure_room(tracker, 'worker')
    assert len(calls) == 1
    monkeypatch.setattr(tracker, '_bd', lambda *args: subprocess.CompletedProcess(args, 0,
        '{"issues":[],"total":10,"has_more":true}', ''))
    with pytest.raises(CapacityUnknown):
        ensure_room(tracker, 'worker')


def test_parallel_task_commands_stop_at_ten(tmp_path):
    root, tracker = world(tmp_path, 9)
    script = 'from shantytown.cli import main; import sys; sys.exit(main(sys.argv[1:]))'
    command = [sys.executable, '-c', script, '--root', str(root), 'task', '-a', 'worker', 'Concurrent']
    processes = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
    results = [process.communicate(timeout=30) for process in processes]
    assert sorted(process.returncode for process in processes) == [cli.OK, cli.REFUSED], results
    assert size(tracker, 'worker') == 10
    assert tracker.get('st-11').assignee is None


def test_crew_text_and_json_expose_count_and_unknown(tmp_path, monkeypatch, capsys):
    root, tracker = world(tmp_path, 9)
    monkeypatch.setattr(cli, 'Tmux', lambda *a, **k: NullPanes())
    assert cli.main(['--root', str(root), 'crew', '--local']) == cli.OK
    assert 'plate: 9/10' in capsys.readouterr().out
    assert cli.main(['--root', str(root), 'crew', '--local', '--json', '--no-priority-advice']) == cli.OK
    rows = json.loads(capsys.readouterr().out)['agents']
    assert rows[0]['plate_size'] == 9 and rows[0]['plate_cap'] == 10
    tracker._path('st-1').write_text('{invalid')
    assert cli.main(['--root', str(root), 'crew', '--local', '--json', '--no-priority-advice']) == cli.OK
    rows = json.loads(capsys.readouterr().out)['agents']
    assert rows[0]['plate_size'] is None


def test_work_update_cannot_bypass_assignment_or_reactivation_cap(tmp_path):
    from argparse import Namespace
    from shantytown.work_item import command
    root, tracker = world(tmp_path)
    pool = tracker.create('Pool')
    args = Namespace(item=pool.id, item_action='update', dry_run=False,
                     assignee='worker', status='in_progress')
    with pytest.raises(PlateFull):
        command(args, tracker)
    assert tracker.get(pool.id).assignee is None
    tracker.update(pool.id, assignee='worker', status='deferred')
    args.assignee = None
    with pytest.raises(PlateFull):
        command(args, tracker)
    assert tracker.get(pool.id).status == 'deferred'


def test_work_update_rechecks_owner_under_assignment_lock(tmp_path):
    from argparse import Namespace
    from shantytown.work_item import command
    root, tracker = world(tmp_path)
    original_get = tracker.get
    moved = False
    def interleaved_get(item_id):
        nonlocal moved
        old = original_get(item_id)
        if not moved:
            moved = True
            tracker.update(item_id, assignee='')
            tracker.create('Replacement', assignee='worker')
        return old
    tracker.get = interleaved_get
    args = Namespace(item='st-1', item_action='update', dry_run=False,
                     assignee='worker', status='in_progress')
    with pytest.raises(PlateFull):
        command(args, tracker)
    assert size(tracker, 'worker') == 10
    assert original_get('st-1').assignee == ''


def test_mixed_seventeen_delivery_records_leave_two_real_slots(tmp_path):
    root, tracker = world(tmp_path, 2)
    for i in range(8):
        tracker.create(f'Recurring alarm: fixture{i}', assignee='worker', labels=['recurring-alarm'])
    for i in range(7):
        tracker.create(f'inbox: fixture{i}', assignee='worker')
    assert size(tracker, 'worker') == 2
    ensure_room(tracker, 'worker')


def test_explicit_delivery_labels_and_legacy_mail_not_real_work():
    from shantytown.plate_capacity import real_work
    for row in ({'title': 'notice', 'labels': ['inbox']},
                {'title': 'notice', 'labels': 'alerting'},
                {'title': 'notice', 'labels': [{'name': 'alarm'}]},
                {'title': 'mail: legacy'}, {'title': 'ALARM: fixture'}):
        assert not real_work(row)
    assert real_work({'title': 'Fix alarm producer', 'labels': ['bug']})


def test_all_tracker_producers_share_admission_and_notify_without_consuming_slot(tmp_path):
    from shantytown.plate_capacity import guard_producers
    root, tracker = world(tmp_path)
    notices = []
    guard_producers(tracker, lambda owner, item: notices.append((owner, item)))
    for title in ('release follow-up', 'workflow follow-up'):
        item = tracker.create(title, assignee='worker')
        assert item.assignee is None
        assert tracker.get(item.id).assignee is None
    message = tracker.create('inbox: hello', assignee='worker')
    alarm = tracker.create('Recurring alarm: fixture', assignee='worker')
    assert message.assignee == alarm.assignee == 'worker'
    assert len(notices) == 2 and size(tracker, 'worker') == 10
    pool = tracker.create('Existing pool work')
    tracker.update(pool.id, assignee='worker', status='in_progress')
    assert tracker.get(pool.id).assignee == ''
    assert tracker.get(pool.id).status == 'open'
    assert len(notices) == 3


def test_producer_uncertain_commit_does_not_repeat_assignment(tmp_path):
    from shantytown.plate_capacity import guard_producers
    root, tracker = world(tmp_path, 9)
    original = tracker.create
    calls = []
    def lost(title, **fields):
        calls.append(original(title, **fields))
        raise TimeoutError('response lost after commit')
    tracker.create = lost
    guard_producers(tracker, lambda *a: None)
    with pytest.raises(TimeoutError):
        tracker.create('One uncertain write', assignee='worker')
    assert len(calls) == 1 and size(tracker, 'worker') == 10


def test_parallel_automatic_producers_share_atomic_host_admission(tmp_path):
    root, tracker = world(tmp_path, 9)
    script = '''from shantytown.files import FilesTracker
from shantytown.plate_capacity import guard_producers
from pathlib import Path
import sys
t = guard_producers(FilesTracker(Path(sys.argv[1])), lambda *a: None)
t.create('automatic work', assignee='worker')
'''
    processes = [subprocess.Popen([sys.executable, '-c', script, str(root/'items')],
                 stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
    results = [p.communicate(timeout=30) for p in processes]
    assert all(p.returncode == 0 for p in processes), results
    assert size(tracker, 'worker') == 10
    assert sorted(tracker.get(f'st-{n}').assignee or '' for n in (10,11)) == ['', 'worker']
