"""Routine transport controls use private inboxes and clocks, no live panes."""
import json
from types import SimpleNamespace as NS

import pytest
from shantytown import admin_inbox as ai
from shantytown.inbox import FilesInbox
from shantytown.tmux import PaneSubmissionUnverified


def setup(tmp_path, monkeypatch):
    card = NS(name='admin', role='administrator', pane='private-pane', retired=False)
    box = FilesInbox(tmp_path / 'inbox')
    sent = []
    panes = NS(exists=lambda p: True, send=lambda p, text: sent.append(text))
    monkeypatch.setattr(ai, 'wait_for', lambda *a, **kw: 900)
    monkeypatch.setattr('shantytown.cli._looks_stranded', lambda *a: False)
    return card, box, sent, panes


@pytest.mark.parametrize('name', ['admin', 'fixture-admin'])
def test_batch_deadline_restart_one_copy_and_ack(tmp_path, monkeypatch, name):
    card, box, sent, panes = setup(tmp_path, monkeypatch)
    card.name = name
    for text in ['routine one', 'routine two']:
        ai.enqueue(tmp_path, card, box.deliver(card.name, text), 'files', 900, now=1000)
    assert ai.sweep(tmp_path, [card], panes, lambda _: box, now=1899) == []
    assert len(box.unread(card.name)) == 2 and sent == []
    # A fresh reader can recover the same queue after process restart.
    recovered = FilesInbox(tmp_path / 'inbox')
    assert len(ai.sweep(tmp_path, [card], panes, lambda _: recovered, now=1900)) == 2
    assert sent == ['routine one\n\nroutine two']
    assert recovered.unread(card.name) == []
    assert ai.sweep(tmp_path, [card], panes, lambda _: recovered, now=2000) == []
    assert len(sent) == 1


@pytest.mark.parametrize('kind', ['unverified', 'stranded', 'ack-error'])
def test_unknown_submission_never_retries_or_loses_pointer(tmp_path, monkeypatch, kind):
    card, box, sent, panes = setup(tmp_path, monkeypatch)
    ai.enqueue(tmp_path, card, box.deliver(card.name, 'routine'), 'files', 10, now=100)
    if kind == 'unverified':
        def fail(*args):
            sent.append('attempted')
            raise PaneSubmissionUnverified('private ambiguous submission')
        panes.send = fail
    elif kind == 'stranded':
        monkeypatch.setattr('shantytown.cli._looks_stranded', lambda *a: True)
    else:
        box.mark_read = lambda *a, **kw: (_ for _ in ()).throw(OSError('private ACK failure'))
    assert ai.sweep(tmp_path, [card], panes, lambda _: box, now=110) == []
    assert len(sent) == 1 and len(box.unread(card.name)) == 1
    assert ai.sweep(tmp_path, [card], panes, lambda _: box, now=111) == []
    assert len(sent) == 1


def test_off_or_unknown_policy_and_clock_reversal_release_early(tmp_path, monkeypatch):
    card, box, sent, panes = setup(tmp_path, monkeypatch)
    ai.enqueue(tmp_path, card, box.deliver(card.name, 'routine'), 'files', 900, now=1000)
    monkeypatch.setattr(ai, 'wait_for', lambda *a, **kw: 0)
    assert len(ai.sweep(tmp_path, [card], panes, lambda _: box, now=1001)) == 1
    ai.enqueue(tmp_path, card, box.deliver(card.name, 'next'), 'files', 900, now=2000)
    monkeypatch.setattr(ai, 'wait_for', lambda *a, **kw: 900)
    assert len(ai.sweep(tmp_path, [card], panes, lambda _: box, now=1999)) == 1
    assert sent == ['routine', 'next']


def test_body_mismatch_or_down_pane_never_acknowledges(tmp_path, monkeypatch):
    card, box, sent, panes = setup(tmp_path, monkeypatch)
    msg = box.deliver(card.name, 'routine')
    ai.enqueue(tmp_path, card, msg, 'files', 10, now=100)
    panes.exists = lambda _: False
    assert ai.sweep(tmp_path, [card], panes, lambda _: box, now=110) == []
    assert len(box.unread(card.name)) == 1
    panes.exists = lambda _: True
    data = json.loads(box._path(msg.id).read_text()); data['body'] = 'changed'
    box._path(msg.id).write_text(json.dumps(data))
    assert ai.sweep(tmp_path, [card], panes, lambda _: box, now=111) == []
    assert sent == [] and len(box.unread(card.name)) == 1


def test_cli_routine_persists_then_scheduled_batch(tmp_path, monkeypatch, capsys):
    from shantytown import cli
    from test_inbox_durable import _root, _RecordingInbox
    box = _RecordingInbox()
    sent = []
    root = _root(tmp_path)
    monkeypatch.setattr(cli, '_inbox', lambda *a, **kw: box)
    monkeypatch.setattr(ai, 'wait_for', lambda *a, **kw: 600)
    monkeypatch.setattr(cli, 'Tmux', lambda *a, **kw: NS(
        exists=lambda p: True, send=lambda p, text: sent.append(text)))
    assert cli.main(['--root', str(root), 'inbox', '-d', '--routine', 'ian', 'progress']) == 0
    assert len(box.delivered) == 1 and sent == [] and box.marked == []
    assert 'pointer remains unread' in capsys.readouterr().out
    assert len(list(ai._directory(root).glob('*.json'))) == 1


def test_routine_requires_durable_and_dry_run_writes_nothing(tmp_path, monkeypatch):
    from shantytown import cli
    from test_inbox_durable import _root
    root = _root(tmp_path)
    monkeypatch.setattr(ai, 'wait_for', lambda *a, **kw: 600)
    monkeypatch.setattr(cli, 'Tmux', lambda *a, **kw: NS(exists=lambda p: True))
    assert cli.main(['--root', str(root), 'inbox', '--routine', 'ian', 'progress']) == 1
    assert cli.main(['--root', str(root), 'inbox', '-d', '--routine', '-n', 'ian', 'progress']) == 0
    assert not ai._directory(root).exists()


@pytest.mark.parametrize('mode,role,harness,lost,last,expected', [
    ('enforce', 'administrator', 'claude', False, 100, 800),
    ('off', 'administrator', 'claude', False, 100, 0),
    ('advise', 'administrator', 'claude', False, 100, 0),
    ('enforce', 'worker', 'claude', False, 100, 0),
    ('enforce', 'administrator', 'codex', False, 100, 0),
    ('enforce', 'administrator', 'claude', True, 100, 0),
    ('enforce', 'administrator', 'claude', False, None, 0),
    ('enforce', 'administrator', 'claude', False, 300, 0),
])
def test_only_explicit_fresh_claude_enforce_defers(tmp_path, monkeypatch,
                                                mode, role, harness, lost, last, expected):
    from shantytown import config, feed_check
    from shantytown import harness as h
    from shantytown.hibernate import WakeLog
    monkeypatch.setattr(config, 'load_or_default', lambda _: (NS(
        admin_wake_budget=NS(mode=mode, agents=['admin'])), None))
    monkeypatch.setattr(h, 'for_card', lambda *a, **kw: NS(name=harness))
    monkeypatch.setattr(feed_check, 'haul_governor_verdict', lambda *a: NS(
        signal_lost=lost, by_window={'seven_day': 93}))
    monkeypatch.setattr(WakeLog, 'last', lambda *a: last)
    assert ai.wait_for(tmp_path, NS(name='admin', role=role), now=200) == expected


def test_batch_preserves_verified_sender_from_actual_cli(tmp_path, monkeypatch):
    from shantytown import cli
    from test_inbox_durable import _root
    root = _root(tmp_path)
    box = FilesInbox(tmp_path / 'private-box')
    sent = []
    panes = NS(exists=lambda _: True, send=lambda p, text: sent.append(text))
    monkeypatch.setattr(cli, '_inbox', lambda *a, **kw: box)
    monkeypatch.setattr(cli, 'Tmux', lambda *a, **kw: panes)
    monkeypatch.setattr(cli, '_verified_sender', lambda *a: ('private-sender', True))
    monkeypatch.setattr(cli, '_looks_stranded', lambda *a: False)
    monkeypatch.setattr(ai, 'wait_for', lambda *a, **kw: 600)
    monkeypatch.setattr(ai.time, 'time', lambda: 1000)
    assert cli.main(['--root', str(root), 'inbox', '-d', '--routine', 'ian', 'progress']) == 0
    assert box.unread('ian')[0].body == '[from private-sender] progress'
    card = NS(name='ian', pane='crew-ian', retired=False)
    assert len(ai.sweep(root, [card], panes, lambda _: box, now=1600)) == 1
    assert sent == ['[from private-sender] progress']
    assert box.unread('ian') == []


@pytest.mark.parametrize('changed', ['pane', 'host'])
def test_recipient_binding_change_does_not_send_to_replacement(tmp_path, monkeypatch, changed):
    card, box, sent, panes = setup(tmp_path, monkeypatch)
    ai.enqueue(tmp_path, card, box.deliver(card.name, 'routine'), 'files', 10, now=100)
    setattr(card, changed, 'replacement')
    assert ai.sweep(tmp_path, [card], panes, lambda _: box, now=110) == []
    assert sent == [] and len(box.unread(card.name)) == 1


def test_retained_pointer_survives_the_batch_ack(tmp_path, monkeypatch):
    # aegis-rwhc #326 review: --routine --retain-pointer must keep its pointer
    # unread after the batch delivers, as the immediate durable send does.
    card, box, sent, panes = setup(tmp_path, monkeypatch)
    kept = box.deliver(card.name, 'retained')
    ai.enqueue(tmp_path, card, kept, 'files', 10, now=100, retain=True)
    ai.enqueue(tmp_path, card, box.deliver(card.name, 'routine'), 'files', 10, now=100)
    assert len(ai.sweep(tmp_path, [card], panes, lambda _: box, now=110)) == 2
    assert sent == ['retained\n\nroutine']
    assert [msg.id for msg in box.unread(card.name)] == [kept.id]
    assert ai.sweep(tmp_path, [card], panes, lambda _: box, now=111) == []
    assert len(sent) == 1


def test_cli_routine_records_retain_pointer(tmp_path, monkeypatch):
    from shantytown import cli
    from test_inbox_durable import _root, _RecordingInbox
    box = _RecordingInbox()
    root = _root(tmp_path)
    monkeypatch.setattr(cli, '_inbox', lambda *a, **kw: box)
    monkeypatch.setattr(ai, 'wait_for', lambda *a, **kw: 600)
    monkeypatch.setattr(cli, 'Tmux', lambda *a, **kw: NS(
        exists=lambda p: True, send=lambda p, text: None))
    assert cli.main(['--root', str(root), 'inbox', '-d', '--routine', '--retain-pointer',
                     'ian', 'progress']) == 0
    [row] = [json.loads(p.read_text()) for p in ai._directory(root).glob('*.json')]
    assert row['retain'] is True and box.marked == []


@pytest.mark.parametrize('old', [19, 20, 25])
def test_already_read_pointers_do_not_starve_newer_progress(tmp_path, monkeypatch, old):
    # aegis-rwhc #326 review: pointers read through the ordinary inbox stay
    # queued (a reader miss is not proof of an ACK). They must not fill the
    # per-batch bound ahead of newer unread progress.
    card, box, sent, panes = setup(tmp_path, monkeypatch)
    stale = [box.deliver(card.name, f'old {n}') for n in range(old)]
    for n, msg in enumerate(stale):
        ai.enqueue(tmp_path, card, msg, 'files', 10, now=100 + n)
    box.mark_read(card.name, ids=[msg.id for msg in stale])
    ai.enqueue(tmp_path, card, box.deliver(card.name, 'new'), 'files', 10, now=500)
    assert len(ai.sweep(tmp_path, [card], panes, lambda _: box, now=510)) == 1
    assert sent == ['new']
    assert len(list(ai._directory(tmp_path).glob('*.json'))) == old


def test_batch_bound_still_applies_to_eligible_pointers(tmp_path, monkeypatch):
    card, box, sent, panes = setup(tmp_path, monkeypatch)
    for n in range(21):
        ai.enqueue(tmp_path, card, box.deliver(card.name, f'p{n}'), 'files', 10, now=100 + n)
    assert len(ai.sweep(tmp_path, [card], panes, lambda _: box, now=200)) == 20
    assert len(ai.sweep(tmp_path, [card], panes, lambda _: box, now=201)) == 1
