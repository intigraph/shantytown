"""Bound jobs cannot answer an approval picker; refusal must stay automatic."""
import pytest
from shantytown import ephemeral as eph, harness
from shantytown.protocols import Agent


@pytest.mark.parametrize('remote', [False, True])
@pytest.mark.parametrize('job', ['task', 'triage', 'review', 'merge'])
def test_bound_codex_job_never_prompts_without_widening_sandbox(tmp_path, remote, job):
    root=tmp_path/'.shanty';root.mkdir()
    (root/'shantytown.toml').write_text('[env]\nSHANTY_REMOTE_CONTROL = '+('"true"' if remote else '"false"')+'\n')
    cfg=root/'settings/codex/worker/config.toml'
    managed=cfg.parent/'packages/standalone/current/codex'
    managed.parent.mkdir(parents=True);managed.write_text('')
    name='eph-'+job+'-abcdef'
    eph.write(root,dict(name=name,job=job,harness='codex',state=eph.LAUNCHING))
    line=harness.get('codex').launch(Agent(name=name,role='worker',workspace='/fixture'),str(cfg),root=root)
    assert '-c approval_policy="never"' in line
    assert 'sandbox_mode="danger-full-access"' not in line
    assert '--dangerously-bypass-approvals-and-sandbox' not in line
    if remote:
        assert 'codex remote-control start -c approval_policy="never" --json' in line


def test_unbound_ordinary_card_keeps_its_operator_policy(tmp_path):
    line=harness.get('codex').launch(Agent(name='ordinary',role='worker'),str(tmp_path/'config.toml'),root=tmp_path)
    assert 'approval_policy=' not in line


@pytest.mark.parametrize('change', [dict(state=eph.DONE), dict(name='eph-task-aaaaaa'), dict(harness='claude')])
def test_unbound_or_ended_record_does_not_change_policy(tmp_path, monkeypatch, change):
    record=dict(name='eph-task-abcdef', job='task', harness='codex', state=eph.LAUNCHING)
    record.update(change)
    monkeypatch.setattr(eph,'read',lambda root,name: record)
    line=harness.get('codex').launch(Agent(name='eph-task-abcdef',role='worker'),str(tmp_path/'config.toml'),root=tmp_path)
    assert 'approval_policy=' not in line
