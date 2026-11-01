"""Obsolete owned text is recoverable even when the board is unavailable."""
import pytest

from shantytown import delivery, inbox_recovery
from test_delivery_custody import local, records
from test_codex_submission import BODY, OWNED, READY, BUSY, keys
from types import SimpleNamespace

ALERT = '\n'.join(['Retained alert, line ' + str(i) for i in range(12)])


def warning_frame(body):
    return ('\x1b[1m›\x1b[0m ' + body + '\n\n'
            '  GPT-6.1-Sol default · /workspace · Review work\n'
            '                                                       ⚠ 1 warning · f2 to view')


def test_warning_footer_uses_the_same_bounded_composer_for_show_and_ownership():
    from shantytown import input_box, triage, tmux
    screen = warning_frame(ALERT)
    assert input_box._classify(screen)[0] == input_box.TYPED
    assert triage.input_state(screen) == triage.INPUT_QUEUED
    assert tmux._codex_owned_input(screen, ALERT)
    assert not tmux._codex_owned_input(warning_frame(ALERT + '\nOperator suffix'), ALERT)


def test_owned_multiline_alert_is_cleared_locally_but_not_acknowledged_or_submitted(tmp_path, monkeypatch):
    panes, calls = local(monkeypatch, tmp_path, [warning_frame(ALERT)])
    body = [ALERT]
    def capture(*a, **kw):
        return warning_frame(body[0]) if body[0].strip() else READY
    def control(pane, key):
        calls.append(['send-keys', pane, key])
        if key == 'C-u':
            lines = body[0].split('\n')
            lines[-1] = ''
            body[0] = '\n'.join(lines)
        elif key == 'BSpace' and body[0].endswith('\n'):
            body[0] = body[0][:-1]
    monkeypatch.setattr(panes, 'capture', capture)
    monkeypatch.setattr(panes, 'control', control)
    with delivery.Custody(tmp_path, 'worker') as custody:
        custody.begin(ALERT, 17)
        custody.finish('queued')
    assert delivery.clear_stalled_owned(tmp_path, SimpleNamespace(pane='worker'), panes)
    [record] = records(tmp_path)
    assert record['text'] == ALERT and record['state'] == 'cleared'
    assert not any(k[-1] in ('Enter', 'Tab', 'Escape', 'C-c') for k in keys(calls))


@pytest.mark.parametrize('session,state,screen,clears', [
    (17, 'superseded', OWNED, True),
    (99, 'superseded', OWNED, False),
    (17, 'delivered', OWNED, False),
    (17, 'superseded', OWNED.replace(BODY, 'Operator draft'), False),
    (17, 'superseded', BUSY, False),
])
def test_local_custody_only_never_needs_a_pointer_or_submits(tmp_path, monkeypatch,
                                                           session, state, screen, clears):
    panes, calls = local(monkeypatch, tmp_path, [screen])
    monkeypatch.setattr(panes, 'session_created', lambda _: session)
    monkeypatch.setattr(panes, 'capture', lambda *a, **kw:
                        READY if any(k[-1] == 'C-u' for k in keys(calls)) else screen)
    with delivery.Custody(tmp_path, 'worker') as custody:
        custody.begin(BODY, 17)
        custody.finish(state)
    assert delivery.clear_superseded(tmp_path, SimpleNamespace(pane='worker'), panes) is clears
    assert records(tmp_path)[0]['state'] == state
    assert not any(k[-1] in ('Enter', 'Tab', 'Escape', 'C-c') for k in keys(calls))
    assert bool(keys(calls)) is clears


def test_every_local_composer_is_examined_before_any_slow_board_read(tmp_path, monkeypatch):
    calls = []
    cards = [SimpleNamespace(name=n, pane=n, retired=False) for n in ['first', 'dispatcher']]
    panes = SimpleNamespace(exists=lambda p: True, foreground=lambda p: 'codex',
        _confirmed_codex=lambda *a: True, capture=lambda *a, **kw: READY)
    monkeypatch.setattr(delivery, 'clear_stalled_owned', lambda r, card, panes:
                        calls.append(('local', card.name)) or False)
    def slow(*args, **kwargs):
        calls.append(('board', args[2].name))
        raise TimeoutError()
    monkeypatch.setattr(delivery, 'supervise', slow)
    inbox_recovery.sweep(cards, panes, None, root=tmp_path)
    assert calls[:2] == [('local', 'first'), ('local', 'dispatcher')]
    assert [c for c in calls if c[0] == 'board'] == [('board', 'first'), ('board', 'dispatcher')]
