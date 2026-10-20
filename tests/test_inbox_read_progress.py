"""Interrupted acknowledgments must retain visible payloads and bounded work."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from shantytown import cli
from shantytown.files import FilesTracker, items
from shantytown.inbox import TrackerInbox


def setup_box(tmp_path, monkeypatch, count=3):
    tracker = FilesTracker(tmp_path / 'items')
    box = TrackerInbox(tracker, lambda: items(tracker))
    messages = [box.deliver('reader', f'payload {i}') for i in range(count)]
    monkeypatch.setattr(cli, '_inbox', lambda *a, **kw: box)
    return tracker, box, messages


def args(**kw):
    return argparse.Namespace(count=False, read=True, read_id=[], dry_run=False, **kw)


def test_large_inbox_is_bounded_and_resumable(tmp_path, monkeypatch, capsys):
    _, box, messages = setup_box(tmp_path, monkeypatch, 96)
    selected = box.unread('reader')[:15]
    assert cli._inbox_read(args(), 'reader') == cli.OK
    assert len(box.unread('reader')) == 81
    out = capsys.readouterr().out
    assert '81 snapshot message(s) not attempted' in out
    assert '[15/15]' in out and 'not atomic' in out
    for m in selected:
        assert m.body in out
    assert cli._inbox_read(args(), 'reader') == cli.OK
    assert len(box.unread('reader')) == 66


def test_new_arrival_is_not_consumed(tmp_path, monkeypatch):
    _, box, _ = setup_box(tmp_path, monkeypatch)
    original = box.unread
    late = []
    def unread(me):
        snapshot = original(me)
        if not late:
            late.append(box.deliver('reader', 'arrived after snapshot'))
        return snapshot
    monkeypatch.setattr(box, 'unread', unread)
    assert cli._inbox_read(args(), 'reader') == cli.OK
    assert box.unread('reader') == late


@pytest.mark.parametrize('landed', [False, True])
def test_unconfirmed_close_is_visible_and_later_closes_continue(tmp_path, monkeypatch, capsys, landed):
    tracker, box, messages = setup_box(tmp_path, monkeypatch)
    original = tracker.update
    def update(id, **kw):
        # stdout must already contain the payload before any write begins.
        out = capsys.readouterr().out
        assert 'payload' in out
        if id == messages[1].id:
            if landed:
                original(id, **kw)
            raise subprocess.TimeoutExpired(['tracker', 'close', id], 30)
        return original(id, **kw)
    monkeypatch.setattr(tracker, 'update', update)
    assert cli._inbox_read(args(), 'reader') == cli.CANNOT_TELL
    result = capsys.readouterr()
    assert 'UNCONFIRMED' in result.err and messages[1].id in result.err
    assert len(box.unread('reader')) == (0 if landed else 1)


def test_keyboard_interrupt_stops_without_hiding_committed_payload(tmp_path, monkeypatch, capsys):
    tracker, box, messages = setup_box(tmp_path, monkeypatch)
    original = tracker.update
    def update(id, **kw):
        original(id, **kw)
        if id == messages[1].id:
            raise KeyboardInterrupt()
    monkeypatch.setattr(tracker, 'update', update)
    assert cli._inbox_read(args(), 'reader') == cli.CANNOT_TELL
    result = capsys.readouterr()
    assert messages[0].body in result.out and messages[1].body in result.out
    assert '1 snapshot message(s) not attempted' in result.out
    assert [m.id for m in box.unread('reader')] == [messages[2].id]
    assert messages[1].id in result.err


def test_selective_preflight_refuses_all_before_any_close(tmp_path, monkeypatch, capsys):
    _, box, messages = setup_box(tmp_path, monkeypatch)
    a = args(); a.read = False; a.read_id = [messages[0].id, 'not-unread']
    assert cli._inbox_read(a, 'reader') == cli.REFUSED
    assert len(box.unread('reader')) == 3
    assert 'Nothing marked read' in capsys.readouterr().err


def test_explicit_selection_is_not_truncated(tmp_path, monkeypatch, capsys):
    _, box, messages = setup_box(tmp_path, monkeypatch, 20)
    a = args(); a.read = False; a.read_id = [m.id for m in messages[:18]]
    assert cli._inbox_read(a, 'reader') == cli.OK
    assert len(box.unread('reader')) == 2
    assert 'Repeat `st inbox --read`' not in capsys.readouterr().out


def test_dry_run_does_not_close(tmp_path, monkeypatch, capsys):
    _, box, _ = setup_box(tmp_path, monkeypatch)
    a = args(); a.dry_run = True
    assert cli._inbox_read(a, 'reader') == cli.OK
    assert len(box.unread('reader')) == 3
    assert '0 writes' in capsys.readouterr().out


def test_sigkill_after_committed_close_retains_flushed_body(tmp_path):
    # Ordinary buffered stdout through a pipe: capsys alone cannot prove flush.
    marker = tmp_path / 'second-close'
    code = '''
import argparse, pathlib, sys, time
from shantytown import cli
from shantytown.inbox import TrackerInbox
from shantytown.protocols import WorkItem
class Tracker:
    def get(self, id):
        return WorkItem(id=id, title='inbox: payload '+id, status='open', assignee='reader')
    def update(self, id, **kw):
        if id == 'two':
            pathlib.Path(sys.argv[1]).write_text('first close committed; second started')
            time.sleep(30)
tracker = Tracker()
box = TrackerInbox(tracker, lambda: [tracker.get(id) for id in ['one', 'two', 'three']])
cli._inbox = lambda *a, **kw: box
cli._inbox_read(argparse.Namespace(count=False, read=True, read_id=[]), 'reader')
'''
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    env.pop('PYTHONUNBUFFERED', None)
    child = subprocess.Popen([sys.executable, '-c', code, str(marker)],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(.01)
        assert marker.exists(), 'child must reach the committed-close control'
    finally:
        child.kill()
        out, err = child.communicate(timeout=5)
    assert child.returncode < 0
    assert b'payload one' in out and b'one: marked read' in out
    assert b'payload two' in out and b'acknowledging two' in out
    assert b'payload three' not in out
    assert not err


def test_named_receipts_do_not_enumerate_even_if_queue_read_fails(tmp_path, monkeypatch, capsys):
    tracker, box, messages = setup_box(tmp_path, monkeypatch)
    box._items = lambda: pytest.fail('named receipt must not enumerate queue')
    box._items_for = lambda *a: pytest.fail('named receipt must not enumerate recipient')
    gets = []
    original = tracker.get
    def get(item_id):
        gets.append(item_id)
        return original(item_id)
    monkeypatch.setattr(tracker, 'get', get)
    a = args(); a.read = False; a.read_id = [messages[0].id, messages[0].id]
    assert cli._inbox_read(a, 'reader') == cli.OK
    assert gets == [messages[0].id, messages[0].id]
    assert tracker.get(messages[0].id).status == 'closed'
    assert tracker.get(messages[1].id).status == 'open'
    out = capsys.readouterr().out
    assert 'other messages not enumerated' in out and 'payload 0' in out


@pytest.mark.parametrize('bad_kind', ['foreign', 'closed', 'ordinary', 'missing'])
def test_named_selection_validates_all_before_any_close(tmp_path, monkeypatch, capsys, bad_kind):
    tracker, box, messages = setup_box(tmp_path, monkeypatch)
    bad = messages[1].id
    if bad_kind == 'foreign': tracker.update(bad, assignee='other')
    elif bad_kind == 'closed': tracker.update(bad, status='closed')
    elif bad_kind == 'ordinary': tracker.update(bad, title='ordinary work')
    else: bad = 'unknown-id'
    box._items = lambda: pytest.fail('no listing fallback')
    writes = []
    monkeypatch.setattr(tracker, 'update', lambda *a, **kw: writes.append((a,kw)))
    a = args(); a.read = False; a.read_id = [messages[0].id, bad]
    assert cli._inbox_read(a, 'reader') == cli.REFUSED
    assert writes == [] and 'Nothing marked read' in capsys.readouterr().err


def test_named_receipt_transport_failure_is_unknown_without_listing_or_close(tmp_path, monkeypatch, capsys):
    tracker, box, messages = setup_box(tmp_path, monkeypatch)
    box._items = lambda: pytest.fail('transport failure cannot trigger listing')
    monkeypatch.setattr(tracker, 'get', lambda *a: (_ for _ in ()).throw(TimeoutError('fixture')))
    monkeypatch.setattr(tracker, 'update', lambda *a, **kw: pytest.fail('no close'))
    a = args(); a.read_id = [messages[0].id]
    assert cli._inbox_read(a, 'reader') == cli.CANNOT_TELL
    assert not capsys.readouterr().out


def test_named_receipt_dry_run_prints_no_false_queue_count(tmp_path, monkeypatch, capsys):
    tracker, box, messages = setup_box(tmp_path, monkeypatch)
    box._items = lambda: pytest.fail('no enumeration')
    a = args(); a.read_id = [messages[0].id]; a.dry_run = True
    assert cli._inbox_read(a, 'reader') == cli.OK
    assert tracker.get(messages[0].id).status == 'open'
    out = capsys.readouterr().out
    assert 'other messages not enumerated' in out and '0 writes' in out


def test_selected_receipt_with_unknown_status_never_closes(tmp_path, monkeypatch, capsys):
    tracker, box, messages = setup_box(tmp_path, monkeypatch)
    tracker.update(messages[0].id, status='alien')
    monkeypatch.setattr(tracker, 'update', lambda *a, **kw: pytest.fail('no close'))
    a = args(); a.read_id = [messages[0].id]
    assert cli._inbox_read(a, 'reader') == cli.CANNOT_TELL
    assert 'status unreadable' in capsys.readouterr().err


def test_count_with_explicit_ids_keeps_whole_queue_read_and_zero_writes(tmp_path, monkeypatch, capsys):
    _, box, messages = setup_box(tmp_path, monkeypatch)
    monkeypatch.setattr(box, 'unread_selected', lambda *a: pytest.fail('count is whole queue'))
    a = args(); a.count = True; a.read_id = [messages[0].id]
    assert cli._inbox_read(a, 'reader') == cli.OK
    assert capsys.readouterr().out.strip() == '3'
    assert len(box.unread('reader')) == 3
