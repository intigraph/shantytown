"""Native and legacy exact receipts for the shared reminder transport."""
from types import SimpleNamespace

import pytest

from shantytown.answer import Answer
from shantytown.inbox import Message, MessageGraphInbox
from shantytown.overdue import PendingReceipt
from shantytown.overdue_ports import ReminderPorts, bind


class Tracker:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def list_messages(self, to, **kwargs):
        self.calls.append((to, kwargs))
        return Answer.complete_read(self.rows, how='exact recipient fixture')


def inbox(rows):
    legacy = SimpleNamespace(find_delivery_receipt=lambda *args: None,
                             find_delivery=lambda *args: None)
    return MessageGraphInbox(legacy, Tracker(rows))


def row(**changes):
    return dict(id='msg-1', to='worker', text='[overdue:fixture] work', read_at=None, **changes)


def test_native_exact_receipt_keeps_read_messages_and_queries_all_registered_windows():
    value = row()
    value['read_at'] = '2026-01-01T00:00:00Z'
    box = inbox([value])
    result = box.find_delivery_receipt('worker', '[overdue:fixture]', 'msg-1')
    assert (result.id, result.to, result.read) == ('msg-1', 'worker', True)
    assert box._tracker.calls == [('worker', {'unread': False, 'all_windows': True})]


@pytest.mark.parametrize('change', [{'to': 'other'}, {'to': None}, {'text': None},
                                    {'text': 'other marker'}, {'text': '[overdue:fixture]x'}])
def test_wrong_or_missing_recipient_marker_is_unknown_not_absent(change):
    value = row()
    value.update(change)
    with pytest.raises(RuntimeError):
        inbox([value]).find_delivery_receipt('worker', '[overdue:fixture]', 'msg-1')


def test_duplicate_and_capped_receipts_refuse_and_absent_remains_read_only():
    for rows in ([row(), row()], [row()] * 10000):
        with pytest.raises(RuntimeError):
            inbox(rows).find_delivery_receipt('worker', '[overdue:fixture]', 'msg-1')
    assert inbox([]).find_delivery_receipt('worker', '[overdue:fixture]', 'msg-1') is None


def test_legacy_exact_receipt_stays_on_existing_reader():
    calls = []
    box = inbox([])
    value = Message(id='example-1', to='worker', body='[overdue:fixture] work', frm='sender')
    box._legacy.find_delivery_receipt = lambda *args: calls.append(args) or value
    assert box.find_delivery_receipt('worker', '[overdue:fixture]', 'example-1') is value
    assert calls == [('worker', '[overdue:fixture]', 'example-1')]
    assert box._tracker.calls == []


def test_shared_ports_confirm_native_receipt_and_retain_uncertain_original_id():
    sent = []
    box = inbox([row()])
    ports = ReminderPorts(lambda: object(), lambda: object(), lambda: box,
                          lambda *args, **kwargs: sent.append((args, kwargs)) or 'msg-1')
    assert ports.deliver('worker', '[overdue:fixture]', 'work') == 'msg-1'
    assert len(sent) == 1
    def failed(*args, **kwargs):
        raise TimeoutError('lost read')
    box._tracker.list_messages = failed
    pending = ports.deliver('worker', '[overdue:fixture]', 'work')
    assert isinstance(pending, PendingReceipt) and pending.identifier == 'msg-1'
    assert len(sent) == 2  # each explicit port call; the shared ledger owns no-resend


def test_ports_do_not_promote_a_wrong_exact_receipt_or_invent_a_sender():
    wrong = SimpleNamespace(id='foreign', to='worker', body='[overdue:fixture] work')
    box = SimpleNamespace(find_delivery_receipt=lambda *args: wrong)
    ports = ReminderPorts(lambda: None, lambda: None, lambda: box, lambda *args, **kwargs: None)
    with pytest.raises(ValueError):
        ports.receipt('worker', '[overdue:fixture]', 'msg-1')


def test_cli_binding_is_lazy_and_reuses_existing_durable_sender(monkeypatch):
    from shantytown import cli
    calls = []
    box = inbox([row()])
    registry = SimpleNamespace(get=lambda name: SimpleNamespace(name=name))
    monkeypatch.setattr(cli, '_inbox', lambda *args, **kwargs: box)
    monkeypatch.setattr(cli, '_registry', lambda *args: registry)
    def persist(target, agent, text, panes, **kwargs):
        calls.append((target.agent, text, kwargs))
        print('delivered to inbox as msg-1')
        return cli.OK
    monkeypatch.setattr(cli, '_inbox_durable', persist)
    args = SimpleNamespace(agent=None, dry_run=True)
    ports = bind(args, object())
    assert calls == []
    assert ports.deliver('worker', '[overdue:fixture]', 'work', boundary_only=True) == 'msg-1'
    assert calls == [('worker', '[overdue:fixture] work', {'sender': 'st fleet tend', 'boundary_only': True})]
    assert args.agent is None and args.dry_run is True
