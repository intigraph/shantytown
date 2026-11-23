"""Enqueue adoption retires the LLM merge lane without mutating live flags."""
from types import SimpleNamespace

import pytest

from shantytown import cli, config, ephemeral as eph


def test_enabled_enqueue_refuses_new_merge_before_lane_or_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(eph, 'lane_refusal', lambda *a: pytest.fail('legacy lane read'))
    with pytest.raises(eph.Refused, match='retired'):
        eph.plan(eph.Request('merge', 'item-1', repo='o/n', pr=1, head='a'*40),
                 root=tmp_path, policy=config.Ephemeral(review_enqueue_enabled=True),
                 actor='boss', administrator='boss', host=None, now=100,
                 role_of=lambda _: 'administrator')
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('enabled', [False, True])
def test_review_jobs_remain_admissible(tmp_path, enabled):
    result = eph.plan(eph.Request('review', 'item-1', repo='o/n', pr=1),
                      root=tmp_path, policy=config.Ephemeral(review_enqueue_enabled=enabled),
                      actor='boss', administrator='boss', host=None, now=100,
                      role_of=lambda _: 'administrator')
    assert result['job'] == 'review'


@pytest.mark.parametrize('broken', [False, True])
def test_legacy_merge_command_refuses_before_remote_reads(tmp_path, monkeypatch, broken):
    policy = config.Ephemeral(review_enqueue_enabled=True)
    monkeypatch.setattr(cli.config, 'load_or_default', lambda _: (
        SimpleNamespace(ephemeral=policy), 'malformed config' if broken else None))
    def forbidden(*a, **kw):
        pytest.fail('retired/unknown policy reached ledger, forge or merge')
    monkeypatch.setattr(eph, 'read', forbidden)
    with pytest.raises(eph.Refused, match='configuration|retired'):
        cli._spawn_merge(SimpleNamespace(root=tmp_path), 'old-merge-job',
                         gh=forbidden, run=forbidden)
