"""A saved checkpoint survives later haul anchors; actor attribution stays exact."""
import os
import subprocess
from types import SimpleNamespace

import pytest
from shantytown import cli, br, feed_check
from shantytown.cycle import Requests
from shantytown.sd import SdTracker


def gate_setup(tmp_path, monkeypatch, comments):
    stamp = tmp_path / 'launched' / 'worker.json'
    stamp.parent.mkdir()
    stamp.write_text('{}')
    os.utime(stamp, (1700000000, 1700000000))
    monkeypatch.setattr(cli, '_backend', lambda *a: 'seeds')
    monkeypatch.setattr(cli, '_tracker', lambda *a: object())
    monkeypatch.setattr(br, 'comments', lambda tracker, bead: comments.get(bead, []))
    return SimpleNamespace(root=tmp_path, checkpoint_bead='handoff')


def test_one_handoff_survives_three_queued_anchors(tmp_path, monkeypatch):
    a = gate_setup(tmp_path, monkeypatch, {'handoff': [
        {'author': 'worker', 'created_at': '2024-01-01T00:00:00Z'}]})
    Requests(tmp_path).request('worker', 'state, next step, rollback', 'handoff')
    for item in ['queued1', 'queued2', 'queued3']:
        monkeypatch.setattr(cli, '_cycle_anchor_bead', lambda *a, iid=item: iid)
        gate = cli._durable_checkpoint_gate(a, 'worker')
        assert gate.ok is True and gate.bead == 'handoff'
    assert 'cycle pending' in feed_check.haul_hold_reason(tmp_path, 'worker')
    assert feed_check.haul_hold_reason(tmp_path, 'another-worker') == ''
    Requests(tmp_path).clear('worker')
    assert feed_check.haul_hold_reason(tmp_path, 'worker') == ''


@pytest.mark.parametrize('comments', [[],
    [{'author': 'shared-user', 'created_at': '2024-01-01T00:00:00Z'}],
    [{'author': 'worker', 'created_at': '2020-01-01T00:00:00Z'}]])
def test_explicit_checkpoint_still_requires_current_agent_handoff(tmp_path, monkeypatch, comments):
    a = gate_setup(tmp_path, monkeypatch, {'handoff': comments})
    monkeypatch.setattr(cli, '_cycle_anchor_bead', lambda *a: 'queued3')
    assert cli._durable_checkpoint_gate(a, 'worker').ok is False


def test_unnamed_checkpoint_still_checks_current_plate(tmp_path, monkeypatch):
    a = gate_setup(tmp_path, monkeypatch, {'current': [
        {'author': 'worker', 'created_at': '2024-01-01T00:00:00Z'}]})
    a.checkpoint_bead = ''
    monkeypatch.setattr(cli, '_cycle_anchor_bead', lambda *a: 'current')
    assert cli._durable_checkpoint_gate(a, 'worker').ok is True


@pytest.mark.real_store  # exercises the adapter; prove_store and subprocess are intercepted
@pytest.mark.parametrize('actor,explicit,expected', [
    ('worker', [], ['--actor', 'worker']),
    ('worker', ['--actor', 'operator'], ['--actor', 'operator']),
    ('worker', ['--actor=operator'], ['--actor=operator']),
    ('', [], []),
])
def test_seeds_comment_transport_uses_session_actor_without_overriding_caller(
        monkeypatch, actor, explicit, expected):
    monkeypatch.setenv('SHANTY_AGENT', actor)
    monkeypatch.setattr(SdTracker, 'prove_store', lambda self: None)
    seen = []
    def run(args, **kw):
        seen.append(args)
        return subprocess.CompletedProcess(args, 0, '', '')
    monkeypatch.setattr('shantytown.sd.subprocess.run', run)
    SdTracker(quipu='http://example.invalid', prefix='test')._bd_in(
        None, *explicit, 'comments', 'add', 'handoff', '--file', 'fixture')
    argv = seen[0]
    assert [a for a in argv if a.startswith('--actor')] == [a for a in expected if a.startswith('--actor')]
    if expected and len(expected) == 2:
        assert argv[argv.index('--actor') + 1] == expected[1]
