"""Durable recovery never converts unrelated input into a submitted prompt."""
from types import SimpleNamespace

import pytest

from shantytown import inbox_recovery, tmux
from shantytown.inbox import Message
from test_codex_submission import BODY, OWNED, READY, BUSY, transport, keys


def setup(monkeypatch, *, frames=None, messages=None):
    panes, calls = transport(monkeypatch, frames or [OWNED, OWNED, OWNED, OWNED, OWNED, BUSY])
    monkeypatch.setattr(panes, 'exists', lambda _: True)
    marked = []
    box = SimpleNamespace(unread=lambda _: messages if messages is not None else [Message('receipt', 'worker', BODY)],
                          mark_read=lambda name, ids: marked.extend(ids))
    card = SimpleNamespace(name='worker', pane='worker', retired=False)
    return panes, calls, box, card, marked


def test_exact_durable_body_starts_and_closes_only_its_pointer(monkeypatch):
    panes, calls, box, card, marked = setup(monkeypatch)
    assert inbox_recovery.sweep([card], panes, box) == [('worker', 'receipt')]
    assert marked == ['receipt']
    assert [c[-1] for c in keys(calls)] == ['Enter']
    assert not any('-l' in c for c in keys(calls))


@pytest.mark.parametrize('messages', [[], [Message('other', 'worker', 'Other text')],
                                      [Message('a', 'worker', BODY), Message('b', 'worker', BODY)]])
def test_absent_foreign_or_ambiguous_receipts_never_submit(monkeypatch, messages):
    panes, calls, box, card, marked = setup(monkeypatch, messages=messages)
    assert inbox_recovery.sweep([card], panes, box) == []
    assert keys(calls) == []
    assert marked == []


def test_changed_composer_never_gets_typed_or_submitted(monkeypatch):
    foreign = OWNED.replace(BODY, 'Foreign operator text')
    panes, calls, box, card, marked = setup(monkeypatch, frames=[OWNED, foreign])
    assert inbox_recovery.sweep([card], panes, box) == []
    assert keys(calls) == []
    assert marked == []


def test_empty_composer_does_not_query_or_deliver_unread_work(monkeypatch):
    panes, calls, box, card, marked = setup(monkeypatch, frames=[READY])
    box.unread = lambda _: pytest.fail('empty composer must not query the store')
    assert inbox_recovery.sweep([card], panes, box) == []
    assert keys(calls) == []


def test_failed_read_keeps_composer_untouched(monkeypatch):
    panes, calls, box, card, marked = setup(monkeypatch)
    def broken(_):
        raise TimeoutError('408')
    box.unread = broken
    assert inbox_recovery.sweep([card], panes, box) == []
    assert keys(calls) == []


def test_unconfirmed_submission_keeps_pointer(monkeypatch):
    panes, calls, box, card, marked = setup(monkeypatch, frames=[OWNED])
    assert inbox_recovery.sweep([card], panes, box) == []
    assert marked == []
    assert [c[-1] for c in keys(calls)] == ['Enter']
