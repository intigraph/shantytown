"""Authoritative lane selection through dispatch and the scheduled feeder."""
from dataclasses import replace
from types import SimpleNamespace as NS

import pytest

from shantytown import cli, config, feed_check, governor as gov, work_class
from shantytown.files import FilesRegistry, FilesTracker
from shantytown.protocols import Agent
from shantytown.tmux import NullPanes


@pytest.mark.parametrize('labels,expected', [
    (['work:design'], True), (['work:important-quipu-code'], True),
    ([], False), (['work:important-code', 'tier:2'], False),
    (['work:docs'], False), (None, False), ('work:design', False),
    ([None, 'work:design'], False),
])
def test_class_is_only_exact_authoritative_labels(labels, expected):
    item = NS(labels=labels, title='Important Quipu design', repository='quipu')
    got, reason = work_class.claude_work_class(item)
    assert got is expected and reason


def world(tmp_path, monkeypatch, enabled=True):
    (tmp_path / 'shantytown.toml').write_text(
        '[governor]\nadmit_class = ' + str(enabled).lower() + '\n')
    reg = FilesRegistry(tmp_path / 'crew')
    for name, lane in [('writer', 'claude'), ('coder', 'codex')]:
        reg.set(Agent(name, pane='%' + name, harness=lane))
    panes = NullPanes()
    monkeypatch.setattr(cli, '_panes', lambda a: panes)
    # These controls concern the real dispatch path, not transport or graph access.
    monkeypatch.setattr(cli, '_go_on_host', lambda *a, **kw: None)
    monkeypatch.setattr(cli, '_graph_context', lambda *a: (NS(render=lambda: 'synthetic graph context'), None))
    monkeypatch.setattr(cli.graph_adoption, 'record', lambda *a, **kw: None)
    return reg, FilesTracker(tmp_path / 'items'), panes


def put(tracker, labels):
    tracker.update('job', title='Important Quipu design', description='Design body',
                   status='open', priority=1, labels=labels)


@pytest.mark.parametrize('labels,target,admitted', [
    (['work:design'], 'writer', False),
    (['work:important-quipu-code'], 'writer', False),
    ([], 'coder', True), (['work:docs'], 'writer', False),
    (['work:important-code', 'tier:2'], 'writer', False),
    (['work:design'], 'coder', True),
    (['work:important-quipu-code'], 'coder', True),
])
def test_real_go_reads_class_before_any_dispatch_write(tmp_path, monkeypatch, labels, target, admitted):
    _, tracker, panes = world(tmp_path, monkeypatch)
    put(tracker, labels)
    before = tracker._path('job').read_bytes()
    result = cli.main(['--root', str(tmp_path), '--backend', 'files',
                       'go', 'job', target] + (['--dry-run'] if admitted else []))
    assert (result == 0) is admitted
    assert tracker._path('job').read_bytes() == before
    assert not panes.sent


def test_key_off_preserves_ordinary_claude_dispatch(tmp_path, monkeypatch):
    _, tracker, _ = world(tmp_path, monkeypatch, enabled=False)
    put(tracker, [])
    assert cli.main(['--root', str(tmp_path), '--backend', 'files',
                     'go', 'job', 'writer', '--dry-run']) == 0
    assert not config.load(tmp_path).governor.admit_class


def test_feed_positive_selection_does_not_trust_ready_labels(tmp_path, monkeypatch):
    reg, tracker, _ = world(tmp_path, monkeypatch)
    put(tracker, [])
    checks = feed_check.worker_governor_admissions(tmp_path, reg, ['writer', 'coder'])
    forged = NS(id='job', priority=1, labels=['work:design'])
    assert checks['writer'](forged)
    assert not checks['coder'](forged)
    put(tracker, ['work:important-quipu-code'])
    # A new scheduling pass re-reads the authoritative row.
    checks = feed_check.worker_governor_admissions(tmp_path, reg, ['writer', 'coder'])
    assert 'important-quipu-code' in checks['writer'](forged)
    assert not checks['coder'](forged)


def test_unreadable_class_is_ordinary_and_not_a_design_permission(tmp_path, monkeypatch):
    reg, _, _ = world(tmp_path, monkeypatch)
    checks = feed_check.worker_governor_admissions(tmp_path, reg, ['writer', 'coder'])
    item = NS(id='missing', priority=1, labels=['work:design'])
    assert 'missing or unreadable' in checks['writer'](item)
    assert not checks['coder'](item)


@pytest.mark.parametrize('role', ['lead', 'administrator', 'keeper'])
def test_class_exemption_cannot_waive_floor_freeze_or_drain(role):
    policy = gov.Policy(admit_class=True, class_exempt=('chief', 'worker'))
    ordinary = NS(id='job', priority=2, labels=[])
    verdict = gov.Verdict(reading=gov.Reading(source='none'))
    chief = Agent('chief', role=role, harness='claude')
    exempt = work_class.for_card(verdict, policy, chief)
    assert bool(exempt.admits(ordinary, 'chief')) is (role != 'administrator')
    worker = work_class.for_card(verdict, policy, Agent('worker', harness='claude'))
    assert worker.admits(ordinary, 'worker')
    floor = gov.Tier(at=50, min_priority=0)
    assert replace(exempt, tier=floor, engaged=(floor,)).admits(ordinary, 'chief')
    assert replace(exempt, frozen=True).admits(ordinary, 'chief')
    drain = gov.Tier(at=90, action='drain')
    assert replace(exempt, tier=drain, engaged=(drain,)).admits(ordinary, 'chief')
    assert replace(worker, exempt=('worker',), tier=floor, engaged=(floor,)).admits(ordinary, 'worker')


def test_sling_keeps_executive_handoff_then_downstream_go_checks_class(tmp_path, monkeypatch):
    reg, tracker, panes = world(tmp_path, monkeypatch)
    reg.set(Agent('chief', 'administrator', roles=('executive',), pane='%chief'))
    put(tracker, ['work:design'])
    monkeypatch.setenv('SHANTY_AGENT', 'author')
    assert cli.main(['--root', str(tmp_path), '--backend', 'files', 'sling', 'job']) == 0
    assert not tracker.get('job').assignee
    assert len(panes.sent) == 1
    assert cli.main(['--root', str(tmp_path), '--backend', 'files',
                     'go', 'job', 'writer', '--dry-run']) != 0
    assert cli.main(['--root', str(tmp_path), '--backend', 'files',
                     'go', 'job', 'coder', '--dry-run']) == 0
    assert len(panes.sent) == 1


def test_configuration_is_explicit_and_strict(tmp_path):
    assert not gov.Policy().admit_class
    for invalid in ['"yes"', '1']:
        (tmp_path / 'shantytown.toml').write_text('[governor]\nadmit_class = ' + invalid)
        with pytest.raises(config.ConfigError):
            config.load(tmp_path)
    (tmp_path / 'shantytown.toml').write_text(
        '[governor]\nadmit_class = true\nclass_exempt = ["chief"]\n')
    policy = config.load(tmp_path).governor
    assert policy.admit_class and policy.class_exempt == ('chief',)


@pytest.mark.parametrize('labels,selected', [([], 'coder'), (['work:design'], 'coder')])
def test_scheduled_feed_returns_only_matching_positive_candidates(tmp_path, monkeypatch, labels, selected):
    reg, tracker, panes = world(tmp_path, monkeypatch)
    put(tracker, labels)
    monkeypatch.setattr(feed_check, 'free_feedable_workers',
                        lambda *a, **kw: ['writer', 'coder'])
    monkeypatch.setattr(feed_check, 'queue_state', lambda *a, **kw: ([
        dict(id='job', title='Important Quipu design', priority=1,
             labels=['work:design'])], []))
    candidates, ready, held = feed_check.gate_inputs(tmp_path, reg, panes, None)
    assert candidates == [selected]
    assert ready == [('job', 'Important Quipu design')]
    assert held == []


def test_assigned_haul_rechecks_authoritative_class(tmp_path, monkeypatch):
    reg, tracker, _ = world(tmp_path, monkeypatch)
    put(tracker, [])
    card = reg.get('writer')
    verdict = work_class.for_card(gov.Verdict(reading=gov.Reading(source='none')),
                                  config.load(tmp_path).governor, card, tmp_path)
    log = []
    assert not feed_check.admitted_haul(
        [dict(id='job', priority=1, labels=['work:design'])], card, verdict,
        log.append, root=tmp_path)
    assert log and 'work class requires codex' in log[0]
    put(tracker, ['work:design'])
    assert not feed_check.admitted_haul([dict(id='job', priority=1)], card,
                                        verdict, log.append, root=tmp_path)
    assert 'work:design' in log[-1]
    coder = reg.get('coder')
    coder_verdict = work_class.for_card(verdict, config.load(tmp_path).governor, coder, tmp_path)
    assert len(feed_check.admitted_haul([dict(id='job', priority=1)], coder,
                                       coder_verdict, log.append, root=tmp_path)) == 1


def test_feeder_uses_effective_policy_not_a_second_local_policy(tmp_path, monkeypatch):
    reg, tracker, _ = world(tmp_path, monkeypatch, enabled=False)
    put(tracker, [])
    effective = NS(governor=gov.Policy(admit_class=True))
    monkeypatch.setattr(cli, '_governors', lambda a: (effective, {}))
    checks = feed_check.worker_governor_admissions(tmp_path, reg, ['writer', 'coder'])
    assert checks['writer'](NS(id='job', priority=1))
    assert not checks['coder'](NS(id='job', priority=1))


def test_bare_governor_cannot_grant_an_unverified_role_exemption(tmp_path):
    policy = gov.Policy(admit_class=True, class_exempt=('worker',))
    verdict = gov.Governor(policy, None).evaluate(persist=False)
    assert verdict.admits(NS(id='job', priority=1, labels=[]), 'worker')


def test_feed_never_falls_back_to_claude_when_only_important_work_is_ready(tmp_path, monkeypatch):
    reg, tracker, panes = world(tmp_path, monkeypatch)
    put(tracker, ['work:important-quipu-code'])
    monkeypatch.setattr(feed_check, 'free_feedable_workers', lambda *a, **kw: ['writer'])
    monkeypatch.setattr(feed_check, 'queue_state', lambda *a, **kw: ([
        dict(id='job', title='Important code', priority=1)], []))
    _, ready, held = feed_check.gate_inputs(tmp_path, reg, panes, None)
    assert ready == []
    assert len(held) == 1 and 'work class requires codex' in held[0][2]
    assert not tracker.get('job').assignee and not panes.sent
