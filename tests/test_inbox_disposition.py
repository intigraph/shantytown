"""Recipient decisions silence delivery, not the underlying incident or evidence."""
import argparse
import json
from types import SimpleNamespace

import pytest

from shantytown import cli
from shantytown.inbox import FilesInbox, Message
from shantytown.inbox_disposition import ControlledInbox, Dispositions, deadline


def setup(tmp_path):
    raw = FilesInbox(tmp_path / 'inbox')
    state = Dispositions(tmp_path, 'files')
    return raw, state, ControlledInbox(raw, state)


def test_34_duplicate_bodies_remain_evidence_but_ack_hides_all(tmp_path):
    raw, state, box = setup(tmp_path)
    messages = [raw.deliver('lead', 'CVE stale [cve:74def8e4]', 'alerting') for _ in range(34)]
    assert len(box.unread('lead')) == 34  # red-side measured baseline
    state.set(messages[0], 'ack', 'already tracked on the security item')
    assert ControlledInbox(raw, Dispositions(tmp_path, 'files')).unread('lead') == []
    assert len(raw.unread('lead')) == 34  # no mass close, incident write or data deletion
    assert raw.find_delivery_receipt('lead', 'CVE', messages[0].id) == messages[0]


def test_defer_releases_only_original_at_deadline_then_receipt_ack_retires_it(tmp_path, monkeypatch):
    raw, state, box = setup(tmp_path)
    original = raw.deliver('lead', 'same body', 'alerting')
    state.set(original, 'defer', 'await maintenance', until=200, now=100)
    duplicates = [raw.deliver('lead', 'same body', 'alerting') for _ in range(33)]
    monkeypatch.setattr('shantytown.inbox_disposition.time.time', lambda: 199)
    assert box.unread('lead') == []
    monkeypatch.setattr('shantytown.inbox_disposition.time.time', lambda: 200)
    assert box.unread('lead') == [original]
    box.mark_read('lead', [original.id])
    assert box.unread('lead') == []
    assert len(raw.unread('lead')) == len(duplicates)


def test_changed_subject_sender_recipient_or_backend_is_not_suppressed(tmp_path):
    raw, state, box = setup(tmp_path)
    message = raw.deliver('lead', 'old body', 'alerting')
    state.set(message, 'ack', 'handled')
    changed = raw.deliver('lead', 'new severity or findings', 'alerting')
    sender = raw.deliver('lead', 'old body', 'human')
    recipient = raw.deliver('worker', 'old body', 'alerting')
    assert box.unread('lead') == [changed, sender]
    assert box.unread('worker') == [recipient]
    assert Dispositions(tmp_path, 'seeds').visible(message)


def test_legacy_attributed_sender_matches_metadata_but_not_other_sender(tmp_path):
    _, state, _ = setup(tmp_path)
    m = Message('old', 'lead', '[from alerting] body', None)
    state.set(m, 'ack', 'handled')
    assert not state.visible(Message('new', 'lead', m.body, 'alerting'))
    assert state.visible(Message('new', 'lead', m.body, 'other'))


@pytest.mark.parametrize('value', [None, '', '2030-01-01', 'nan', '1970-01-01T00:00:00Z'])
def test_deadline_requires_bounded_future_timezone(value):
    with pytest.raises(ValueError):
        deadline(value, now=100)


def test_corrupt_state_never_claims_quiet_or_overwrites_prior_decision(tmp_path):
    raw, state, box = setup(tmp_path)
    m = raw.deliver('lead', 'body', 'sender')
    state.set(m, 'ack', 'handled')
    state._path(m).write_text('{}')
    with pytest.raises(ValueError):
        box.unread('lead')
    with pytest.raises(ValueError):
        state.set(m, 'ack', 'new reason')
    assert state._path(m).read_text() == '{}'


def args(root, **changes):
    base = dict(root=root, backend='files', agent='lead', message=[], dry_run=False,
                ack_id=None, defer_id=None, until=None, reason='tracked elsewhere')
    return argparse.Namespace(**(base | changes))


def test_cli_recipient_owns_disposition_and_dry_run_has_no_writes(tmp_path, monkeypatch):
    raw, state, box = setup(tmp_path)
    m = raw.deliver('lead', 'body', 'alerting')
    monkeypatch.setattr(cli, '_inbox', lambda *a, **kw: box)
    monkeypatch.setenv('SHANTY_AGENT', 'other')
    assert cli._inbox_dispose(args(tmp_path, ack_id=m.id)) == cli.REFUSED
    monkeypatch.setenv('SHANTY_AGENT', 'lead')
    assert cli._inbox_dispose(args(tmp_path, ack_id=m.id, dry_run=True)) == cli.OK
    assert not state.directory.exists()
    assert cli._inbox_dispose(args(tmp_path, ack_id=m.id)) == cli.OK
    assert box.unread('lead') == []
    assert raw.unread('lead') == [m]


def test_cli_missing_receipt_or_defer_deadline_refuses_without_write(tmp_path, monkeypatch):
    raw, state, box = setup(tmp_path)
    m = raw.deliver('lead', 'body', 'alerting')
    monkeypatch.setattr(cli, '_inbox', lambda *a, **kw: box)
    monkeypatch.setenv('SHANTY_AGENT', 'lead')
    assert cli._inbox_dispose(args(tmp_path, ack_id='missing')) == cli.REFUSED
    assert cli._inbox_dispose(args(tmp_path, defer_id=m.id)) == cli.REFUSED
    assert not state.directory.exists()


def test_durable_sender_repeats_do_not_persist_or_submit_even_after_defer_expiry(tmp_path, monkeypatch):
    raw, state, box = setup(tmp_path)
    m = raw.deliver('lead', 'body', 'alerting')
    state.set(m, 'defer', 'wait', now=100, until=200)
    monkeypatch.setenv('SHANTY_AGENT', 'alerting')
    monkeypatch.setattr(cli, '_inbox', lambda *a, **kw: box)
    monkeypatch.setattr('shantytown.inbox_disposition.time.time', lambda: 250)
    card = SimpleNamespace(name='lead', host=None, pane='pane', role='worker')
    class Panes:
        def exists(self, pane): return True
        def send(self, *a): raise AssertionError('suppressed repeat must not type')
    for _ in range(34):
        assert cli._inbox_durable(args(tmp_path), card, 'body', Panes()) == cli.OK
    assert raw.unread('lead') == [m]
    assert box.unread('lead') == [m]  # original ready for ordinary delivery


def test_bounded_view_keeps_stored_count_and_selected_reader_filters(tmp_path):
    raw, state, box = setup(tmp_path)
    m = raw.deliver('lead', 'body', 'sender')
    state.set(m, 'ack', 'handled')
    assert box.unread_view('lead') == (1, [])
    assert box.unread_selected('lead', [m.id]) == []


def test_already_delivered_receipt_can_be_acked_or_deferred_and_wakes_once(tmp_path, monkeypatch):
    raw, state, box = setup(tmp_path)
    m = raw.deliver('lead', 'already live', 'alerting')
    raw.mark_read('lead', [m.id])
    monkeypatch.setattr(cli, '_inbox', lambda *a, **kw: box)
    monkeypatch.setenv('SHANTY_AGENT', 'lead')
    monkeypatch.setattr('shantytown.inbox_disposition.time.time', lambda: 100)
    assert cli._inbox_dispose(args(tmp_path, defer_id=m.id,
        until='1970-01-01T00:03:20Z')) == cli.OK
    assert box.unread('lead') == []
    monkeypatch.setattr('shantytown.inbox_disposition.time.time', lambda: 200)
    assert [v.id for v in box.unread('lead')] == [m.id]
    assert [v.id for v in box.mark_read('lead', [m.id])] == [m.id]
    assert box.unread('lead') == []
    assert raw.get_message('lead', m.id).read
    assert cli._inbox_dispose(args(tmp_path, ack_id=m.id)) == cli.OK


def test_exact_receipt_reader_refuses_foreign_receipt(tmp_path):
    raw, _, _ = setup(tmp_path)
    m = raw.deliver('other', 'private', 'sender')
    with pytest.raises(ValueError):
        raw.get_message('lead', m.id)


def test_native_exact_receipt_reader_and_message_graph_no_mailbox_scan(tmp_path, monkeypatch):
    import subprocess
    from shantytown.sd import SdTracker
    from shantytown.inbox import MessageGraphInbox
    from shantytown.answer import Answer
    calls = []
    row = dict(id='msg-exact', to='lead', text='native', read_at='2026-11-14T00:00:00Z', **{'from':'sender'})
    tracker = object.__new__(SdTracker)
    def execute(*argv):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, json.dumps(row), '')
    monkeypatch.setattr(tracker, '_bd', execute)
    native = MessageGraphInbox(None, tracker)
    message = native.get_message('lead', 'msg-exact')
    assert message.read and message.body == 'native'
    assert calls == [('msg', 'show', 'msg-exact', '--all-windows', '--json')]
    with pytest.raises(ValueError):
        native.get_message('other', 'msg-exact')
    row['id'] = 'msg-wrong'
    with pytest.raises(RuntimeError):
        native.get_message('lead', 'msg-exact')


def test_tracker_exact_receipt_reader_includes_closed_but_checks_owner(tmp_path):
    from shantytown.files import FilesTracker, items
    from shantytown.inbox import TrackerInbox
    tracker = FilesTracker(tmp_path / 'items')
    box = TrackerInbox(tracker, lambda: items(tracker))
    message = box.deliver('lead', 'old receipt', 'sender')
    box.mark_read('lead', [message.id])
    assert box.get_message('lead', message.id).read
    with pytest.raises(ValueError):
        box.get_message('other', message.id)
