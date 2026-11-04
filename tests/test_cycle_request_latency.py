"""Fresh file feeds advice without redundant tracker reads; executor gates remain."""
import os
from types import SimpleNamespace

import pytest
from shantytown import cli, cycle, br, handoff_text
from tests.test_self_cycle_performs import admin, _args


def test_file_posts_once_and_quality_uses_supplied_text(admin, monkeypatch, capsys):
    root, plate = admin
    plate['bead'] = 'task'
    notes = root / 'notes'; notes.write_text('task: next\nLanded: A\nLocal: B\nDecisions: none')
    stamp = root / 'launched/hammond.json'; stamp.parent.mkdir(); stamp.write_text('{}')
    os.utime(stamp, (1700000000, 1700000000))
    monkeypatch.setattr(cli, '_backend', lambda *a: 'seeds')
    posted = []; judged = []
    monkeypatch.setattr(br, 'append_comment', lambda tracker, target, body: posted.append((target, body)))
    monkeypatch.setattr(cli, '_durable_checkpoint_gate', lambda *a: pytest.fail('redundant plate/comments read'))
    monkeypatch.setattr(cli, '_checkpoint_quality_gate', lambda a, who, text, session: judged.append((text, session)) or (True, ''))
    monkeypatch.setattr(cli, '_spawn_self_cycle_server', lambda *a: '')
    assert cli._cmd_cycle(_args(root, checkpoint_file=str(notes), checkpoint_bead='task')) == cli.OK
    assert posted == [('task', notes.read_text())]
    assert judged == [(notes.read_text(), '2023-11-14T22:13:20+00:00')]
    assert cycle.Requests(root).pending()['hammond']['checkpoint_bead'] == 'task'
    assert 'Do not poll or reissue this accepted request' in capsys.readouterr().out


def test_reason_only_keeps_existing_durable_lookup(admin, monkeypatch):
    root, plate = admin
    plate['bead'] = 'task'
    judged = []
    monkeypatch.setattr(cli, '_durable_checkpoint_gate', lambda *a: SimpleNamespace(checkpoint='stored handoff', since='launch'))
    monkeypatch.setattr(cli, '_checkpoint_quality_gate', lambda a, who, text, session: judged.append((text, session)) or (True, ''))
    monkeypatch.setattr(cli, '_spawn_self_cycle_server', lambda *a: '')
    assert cli._cmd_cycle(_args(root, reason='pointer')) == cli.OK
    assert judged == [('stored handoff', 'launch')]


def test_unknown_launch_does_not_fabricate_quality_session(admin, monkeypatch):
    root, plate = admin
    notes = root / 'notes'; notes.write_text('checkpoint')
    plate['bead'] = 'task'
    monkeypatch.setattr(cli, '_backend', lambda *a: 'seeds')
    monkeypatch.setattr(br, 'append_comment', lambda *a: None)
    def unreadable(*a): raise PermissionError('fixture')
    monkeypatch.setattr(cli, '_cycle_session_start', unreadable)
    seen = []
    monkeypatch.setattr(cli, '_checkpoint_quality_gate', lambda a, who, text, session: seen.append(session) or (True, ''))
    monkeypatch.setattr(cli, '_spawn_self_cycle_server', lambda *a: '')
    assert cli._cmd_cycle(_args(root, checkpoint_file=str(notes))) == cli.OK
    assert seen == ['']


@pytest.mark.parametrize('text', [handoff_text.cycle_now(450,400), handoff_text.haul_handoff(450,400), handoff_text.coordinator_self_handoff(450,400)])
def test_cycle_recipe_has_one_posting_command_and_explicit_context(text):
    assert text.count('st agent cycle --self') == 1
    assert 'st work item comment' not in text
    assert '--checkpoint-file' in text and '--checkpoint-bead' in text and '--quipu-node' in text
    assert 'st ops help handoff' in text


def test_builtin_help_includes_template_and_requires_idle_after_acceptance():
    from shantytown import help_topics
    text = help_topics.render('handoff')
    assert handoff_text.CHECKPOINT_TEMPLATE in text
    assert 'keep working until it fires' not in text
    assert 'END YOUR TURN' in text and 'do not poll or reissue' in text
    assert 'only once your pane is idle' in text
    assert 'Do not separately' in text
