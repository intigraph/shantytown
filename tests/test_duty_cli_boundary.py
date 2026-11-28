"""Actual CLI consumers must enforce the already-reviewed duty contract."""
from types import SimpleNamespace
import time

import pytest

from shantytown import cli, crew_rules, due_brief, feed_hold, ephemeral, context_hint
from shantytown.duties import Duties, KINDS
from shantytown.files import write_json_atomic
from tests.test_stranded_duties import armed, install, record
from tests.test_stranded_adapter import setup


def stop_world(world, monkeypatch):
    world = armed(world, monkeypatch)
    install(world, [record()])
    world.panes.exists = lambda _: False
    monkeypatch.setattr(cli, '_registry', lambda _: world.registry)
    monkeypatch.setattr(cli, '_panes', lambda _: world.panes)
    monkeypatch.setattr(cli, '_tracker', lambda _: world.tracker)
    monkeypatch.setattr(cli, '_inbox', lambda _: world.inbox)
    return world


def test_stop_parser_accepts_explicit_disposition():
    parser = cli.build_parser()
    assert parser.parse_args(['agent', 'stop', 'worker', '--repool-work']).repool_work
    assert not parser.parse_args(['agent', 'stop', 'worker']).repool_work


@pytest.mark.parametrize('dry_run', [False, True])
def test_cli_refuses_held_duty_before_stop_callback(setup, monkeypatch, dry_run):
    world = stop_world(setup, monkeypatch)
    stopped = []
    monkeypatch.setattr(cli, '_stop_locked', lambda _: stopped.append(True) or 0)
    args = SimpleNamespace(root=world.root, agent='worker', dry_run=dry_run,
                           repool_work=False)
    assert cli._cmd_stop(args) == cli.REFUSED
    assert stopped == [] and world.repairs == {}


def test_cli_repool_completes_external_repair_before_stop(setup, monkeypatch):
    world = stop_world(setup, monkeypatch)
    stopped = []
    def stop(_):
        assert len(world.repairs) == len(world.inbox.unread('admin')) == 1
        assert world.row['assignee'] == 'worker'  # ASK remains owned.
        stopped.append(True)
        return 0
    monkeypatch.setattr(cli, '_stop_locked', stop)
    args = SimpleNamespace(root=world.root, agent='worker', dry_run=False,
                           repool_work=True)
    assert cli._cmd_stop(args) == cli.OK
    assert stopped == [True]


def test_cli_unknown_census_does_not_stop(setup, monkeypatch):
    world = stop_world(setup, monkeypatch)
    def unknown(_):
        raise OSError('synthetic unavailable census')
    world.tracker.stranded_rows = unknown
    monkeypatch.setattr(cli, '_stop_locked', lambda _: pytest.fail('stop occurred'))
    args = SimpleNamespace(root=world.root, agent='worker', dry_run=False,
                           repool_work=True)
    assert cli._cmd_stop(args) == cli.CANNOT_TELL


def test_internal_cycle_preserves_existing_bypass(setup, monkeypatch):
    world = stop_world(setup, monkeypatch)
    monkeypatch.setattr(cli, '_stop_locked', lambda _: 17)
    args = SimpleNamespace(root=world.root, agent='worker', dry_run=False,
                           _cycle_internal_stop=True)
    assert cli._cmd_stop(args) == 17
    assert world.repairs == {}


def anchor_world(root, monkeypatch, role):
    projection = SimpleNamespace(me=SimpleNamespace(role=role), item=None,
                                 render=lambda: 'fixture anchor')
    monkeypatch.setattr(cli, '_me', lambda _: 'admin')
    monkeypatch.setattr(cli, '_resolve_anchor', lambda *_, **_kwargs: (
        projection, SimpleNamespace(store=None), SimpleNamespace(get=lambda _: None)))
    monkeypatch.setattr(cli.plate_publish, 'publish', lambda *_a, **_k: None)
    monkeypatch.setattr(cli.plate_publish, 'own_session', lambda: None)
    monkeypatch.setattr(crew_rules, 'load', lambda *_: [])
    monkeypatch.setattr(crew_rules, 'render', lambda _: '')
    monkeypatch.setattr(due_brief, 'load', lambda *_: [])
    monkeypatch.setattr(due_brief, 'render', lambda *_a, **_k: '')
    monkeypatch.setattr(feed_hold, 'reason', lambda *_: None)
    monkeypatch.setattr(ephemeral, 'live', lambda *_: [])
    monkeypatch.setattr(ephemeral, 'render', lambda *_: [])
    monkeypatch.setattr(context_hint, 'crew_label', lambda *_: '')
    return SimpleNamespace(root=root)


@pytest.mark.parametrize('role', ['administrator', 'worker'])
@pytest.mark.parametrize('fresh', [False, True])
def test_anchor_renders_real_census_only_for_administrator(tmp_path, monkeypatch,
                                                         capsys, role, fresh):
    args = anchor_world(tmp_path, monkeypatch, role)
    report = Duties(tmp_path).root / 'report.json'
    report.parent.mkdir(parents=True)
    counts = dict.fromkeys(KINDS, 0)
    counts['merge-queue'] = 2
    write_json_atomic(report, dict(complete=True, checked_at=time.time() - (0 if fresh else 1000),
                                  orphaned=counts))
    before = report.read_bytes()
    assert cli._cmd_anchor(args) == cli.OK
    output = capsys.readouterr().out
    expected = 'Duties: 2 orphaned' if fresh else 'Duties: UNKNOWN'
    assert (expected in output) is (role == 'administrator')
    assert report.read_bytes() == before
