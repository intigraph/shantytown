"""Restored author lanes must agree in dispatch, scheduled feed and owned haul."""
from dataclasses import replace
from types import SimpleNamespace as NS

import pytest

from shantytown import cli, feed_check, governor as gov, work_class
from shantytown.protocols import Agent
from test_work_class import put, world


@pytest.mark.parametrize('labels', [[], ['work:docs'], ['work:design'],
    ['work:important-quipu-code'], ['work:claude-authorized'],
    ['work:design', 'work:claude-authorized']])
@pytest.mark.parametrize('target', ['writer', 'coder'])
def test_any_author_class_uses_normal_private_dispatch(tmp_path, monkeypatch, labels, target):
    _, tracker, panes = world(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, '_graph_context', lambda *a: (
        NS(render=lambda: 'private graph fixture', nodes=('fixture',)), None))
    put(tracker, labels)
    assert cli.main(['--root', str(tmp_path), '--backend', 'files', 'go', 'job', target]) == 0
    assert tracker.get('job').assignee == target
    assert len(panes.sent) == 1


@pytest.mark.parametrize('review', [False, True])
@pytest.mark.parametrize('authorized', [False, True])
def test_feed_and_haul_use_exact_review_class(tmp_path, monkeypatch, review, authorized):
    reg, tracker, panes = world(tmp_path, monkeypatch)
    labels = ['work:review'] if review else []
    if authorized:
        labels += ['work:design', 'work:claude-authorized']
    put(tracker, labels)
    # The ready snapshot lies in both directions; only the exact tracker wins.
    snapshot = NS(id='job', priority=1, labels=[] if review else ['work:review'])
    checks = feed_check.worker_governor_admissions(tmp_path, reg, ['writer', 'coder'])
    assert bool(checks['writer'](snapshot)) is review
    assert not checks['coder'](snapshot)
    for name in ['writer', 'coder']:
        card = reg.get(name)
        verdict = work_class.for_card(gov.Verdict(reading=gov.Reading(source='none')),
                                      gov.Policy(admit_class=True), card, tmp_path)
        selected = feed_check.admitted_haul([vars(snapshot)], card, verdict,
                                            lambda _: None, root=tmp_path)
        assert bool(selected) is (name == 'coder' or not review)
    assert not tracker.get('job').assignee and not panes.sent


@pytest.mark.parametrize('labels', [['work:review'],
    ['work:review', 'work:design', 'work:claude-authorized']])
def test_review_cannot_use_claude_administrator_exception(labels):
    policy = gov.Policy(admit_class=True, class_exempt=('chief',))
    for lane in ['claude', 'codex']:
        verdict = work_class.for_card(gov.Verdict(reading=gov.Reading(source='none')),
            policy, Agent('chief', role='administrator', harness=lane))
        assert bool(verdict.admits(NS(id='review', priority=0, labels=labels), 'chief')) is (lane == 'claude')


@pytest.mark.parametrize('lane', ['claude', 'codex'])
@pytest.mark.parametrize('restriction', ['floor', 'freeze', 'drain'])
def test_restored_authoring_never_waives_budget_gates(lane, restriction):
    verdict = gov.Verdict(reading=gov.Reading(source='none'), admit_class=True, work_harness=lane)
    item = NS(id='ordinary', priority=2, labels=[])
    assert not verdict.admits(item, 'author')
    if restriction == 'freeze':
        verdict = replace(verdict, frozen=True)
    else:
        tier = gov.Tier(at=50, min_priority=0) if restriction == 'floor' else gov.Tier(at=90, action='drain')
        verdict = replace(verdict, tier=tier, engaged=(tier,))
    assert verdict.admits(item, 'author')
