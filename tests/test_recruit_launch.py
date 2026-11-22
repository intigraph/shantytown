"""Real signature/store/planner/ledger, synthetic enrollment/forge/launcher.

No protected UID is installed and no pane, privileged helper or service starts.
"""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from shantytown import cli, config, ephemeral, job_context, recruit_launch as bridge
from shantytown import recruit_store as rs
from shantytown.actor_identity import IdentityError
from shantytown.tmux import NullPanes
from test_recruit_store import private_store  # noqa: F401
from test_recruit_handoff import ctx  # noqa: F401


@pytest.fixture
def native(ctx, monkeypatch):
    policy = replace(ctx.kwargs['policy'], recruitment_launch_ready=True,
                     harness_by_job={'review': 'claude'})
    ctx.kwargs['policy'] = policy
    root = Path(ctx.pin.root)
    crew = root / 'crew'
    crew.mkdir(exist_ok=True)
    (crew / 'fixture-admin.json').write_text(json.dumps({
        'role': 'administrator', 'host': ctx.pin.host, 'dangerous': True}))
    workspace = root / 'isolated-job'
    workspace.mkdir()
    ctx.selected[0]['workspace'] = str(workspace)
    cfg = replace(config.Config(), ephemeral=policy, host_name=ctx.pin.host)
    monkeypatch.setattr(config, 'load_or_default', lambda _: (cfg, None))
    monkeypatch.setattr(cli, '_spawn_actor', lambda **_: 'fixture-admin')
    monkeypatch.setattr(cli, '_spawn_inside', lambda *a, **kw: None)
    monkeypatch.setattr(cli, '_spawn_item_work_request', lambda a, item: deepcopy(ctx.custody))
    monkeypatch.setattr(cli, '_spawn_item_context', lambda *a: 'fixture context')
    monkeypatch.setattr(cli, '_spawn_governor_refusal', lambda *a: '')
    monkeypatch.setattr(cli, '_spawn_checkout', lambda _: None)
    monkeypatch.setattr(job_context, 'collect', lambda *a: {})
    monkeypatch.setattr(job_context, 'current_comments', lambda *a: [])
    monkeypatch.setattr(cli, '_runtime', lambda *a: None)
    monkeypatch.setattr(cli, '_panes', lambda *a: NullPanes())
    def select(req, **kw):
        ctx.calls.append('native-select' if kw['native_probe'] else 'recheck-select')
        return deepcopy(ctx.selected)
    monkeypatch.setattr(bridge.job_launch, 'select', select)
    launched, ended = [], []
    def launch(args, card, panes, runtime):
        record = ephemeral.read(root, card.name)
        assert record['state'] == ephemeral.LAUNCHING
        assert (crew / (card.name + '.json')).exists()
        launched.append(record)
        args._startup_delivered = True
        return cli.OK
    monkeypatch.setattr(cli, '_launch', launch)
    def end(args, name, *a, **kw):
        ended.append(name)
        record = ephemeral.read(root, name)
        record['state'] = ephemeral.DONE
        ephemeral.write(root, record)
        (crew / (name + '.json')).unlink()
        return record, []
    monkeypatch.setattr(cli, '_spawn_end', end)
    ctx.args = cli.build_parser().parse_args(['--root', str(root), 'agent', 'spawn', '--ephemeral'])
    ctx.launched, ctx.ended, ctx.cfg = launched, ended, cfg
    return ctx


def call(native):
    return bridge.launch(native.signed(), args=native.args, **native.kwargs)


def states(native):
    with rs.Store(native.pin) as store:
        return store.db.execute('SELECT state FROM operations').fetchall()


def test_existing_spawn_writes_ledger_and_card_before_one_launch(native):
    receipt = call(native)
    assert receipt['live'] and receipt['state'] == 'launched'
    assert receipt['name'] == 'eph-review-abcdef'
    assert len(native.launched) == 1 and not native.ended
    record = ephemeral.read(native.pin.root, receipt['name'])
    assert record['state'] == ephemeral.LIVE and record['head'] == native.body['head']
    assert record['recruiter']['principal'] == native.pin.principal
    assert native.calls == ['admit', 'native-select', 'admit', 'recheck-select',
                            'admit', 'recheck-select']
    assert states(native) == [('launched',)]
    with pytest.raises(IdentityError, match='replay'):
        call(native)
    native.body['nonce'] = 'c' * 64
    with pytest.raises(IdentityError, match='already claimed'):
        call(native)
    assert len(native.launched) == 1


def test_default_activation_gate_refuses_before_nonce_store(native):
    native.kwargs['policy'] = replace(native.kwargs['policy'], recruitment_launch_ready=False)
    with pytest.raises(IdentityError, match='activation is gated'):
        call(native)
    assert not (native.directory / rs.NAME).exists() and not native.launched


def test_actual_spawn_config_must_also_admit_activation(native, monkeypatch):
    cfg = replace(native.cfg, ephemeral=replace(native.cfg.ephemeral, recruitment_launch_ready=False))
    monkeypatch.setattr(config, 'load_or_default', lambda _: (cfg, None))
    assert call(native)['state'] == 'refused'
    assert states(native) == [('refused',)] and not native.launched


@pytest.mark.parametrize('gate', ['unattended', 'unattended_uid_ready', 'require_verified_identity'])
def test_actual_spawn_identity_gates_remain_required(native, monkeypatch, gate):
    cfg = replace(native.cfg, ephemeral=replace(native.cfg.ephemeral, **{gate: False}))
    monkeypatch.setattr(config, 'load_or_default', lambda _: (cfg, None))
    assert call(native)['state'] == 'refused'
    assert not native.launched


@pytest.mark.parametrize('gate', ['quiet', 'quiet-unknown', 'maintenance', 'governor'])
def test_existing_window_and_governor_can_refuse_before_launch(native, monkeypatch, gate):
    from types import SimpleNamespace
    if gate.startswith('quiet'):
        monkeypatch.setattr(bridge.recruit_handoff.quiet_time, 'read', lambda _: SimpleNamespace(
            held=gate == 'quiet', state='unknown' if gate == 'quiet-unknown' else 'active', entries=()))
    elif gate == 'maintenance':
        monkeypatch.setattr(bridge.recruit_handoff.window, 'active', lambda _: {'state': 'active'})
    else:
        monkeypatch.setattr(cli, '_spawn_governor_refusal', lambda *a: 'fixture governor refusal')
    assert call(native)['state'] == 'refused'
    assert not native.launched


@pytest.mark.parametrize('selector', ['report', 'merge', 'reap', 'stop', 'retry',
    'recruiter', 'recruitment_prepare', 'recruitment_request', 'dry_run', 'harness', 'checkout'])
def test_second_operation_and_sender_launcher_options_are_refused(native, selector):
    setattr(native.args, selector, True)
    with pytest.raises(IdentityError, match='selectors refused'):
        call(native)
    assert states(native) == [('unknown',)] and not native.launched


@pytest.mark.parametrize('boundary', [2, 3])
@pytest.mark.parametrize('change', ['expiry', 'custody', 'key', 'forge', 'quiet'])
def test_rechecks_before_ledger_and_before_launch_refuse_changes(native, monkeypatch, boundary, change):
    now, calls = [110], [0]
    native.kwargs['clock'] = lambda: now[0]
    def admit(req, **kw):
        calls[0] += 1
        if calls[0] != boundary:
            return
        if change == 'expiry': now[0] = 160
        elif change == 'custody': native.custody['revision'] = 'f' * 40
        elif change == 'key':
            monkeypatch.setattr(bridge.recruit_request, 'load_controller_binding',
                                lambda: replace(native.pin, public_key=b'x' * 32))
        elif change == 'quiet':
            from types import SimpleNamespace
            monkeypatch.setattr(bridge.recruit_handoff.quiet_time, 'read', lambda _: SimpleNamespace(
                held=True, state='active', entries=()))
        else: raise IdentityError('fixture fresh forge refuses')
    monkeypatch.setattr(bridge.recruiter, 'cli_admit', admit)
    assert call(native)['state'] == 'refused'
    assert not native.launched and states(native) == [('refused',)]
    assert native.ended == (['eph-review-abcdef'] if boundary == 3 else [])


def test_selected_capability_change_refuses_before_ledger(native, monkeypatch):
    calls = [0]
    def select(req, **kw):
        calls[0] += 1
        value = deepcopy(native.selected)
        if calls[0] == 2: value[0]['uid'] += 1
        return value
    monkeypatch.setattr(bridge.job_launch, 'select', select)
    assert call(native)['state'] == 'refused'
    assert not native.launched and not native.ended
    assert not list(Path(native.pin.root).glob('ephemeral/eph-*.json'))


@pytest.mark.parametrize('identity', ['recruiter', 'controller'])
def test_job_uid_must_differ_from_both_processes(native, identity):
    import os
    native.selected[0]['uid'] = native.pin.uid if identity == 'recruiter' else os.geteuid()
    assert call(native)['state'] == 'refused' and not native.launched


def test_launch_exception_retains_unknown_and_never_rearms(native, monkeypatch):
    def lost(*a, **kw):
        raise RuntimeError('fixture launch response lost')
    monkeypatch.setattr(cli, '_launch', lost)
    with pytest.raises(RuntimeError, match='response lost'):
        call(native)
    assert states(native) == [('unknown',)]
    assert ephemeral.read(native.pin.root, 'eph-review-abcdef')['state'] == ephemeral.LAUNCHING
    with pytest.raises(IdentityError, match='replay'):
        call(native)


def test_success_code_without_real_live_ledger_is_not_a_receipt(native, monkeypatch):
    monkeypatch.setattr(cli, '_cmd_spawn', lambda *a, **kw: cli.OK)
    with pytest.raises((IdentityError, TypeError)):
        call(native)
    assert states(native) == [('unknown',)]


def test_prepared_receipt_is_never_execution_input(native):
    with pytest.raises(IdentityError):
        bridge.launch({'state': 'prepared', 'execution': 'refused', 'operation': 'a' * 64},
                      args=native.args, **native.kwargs)
    assert not native.launched


def test_config_gate_is_false_by_default_and_strict_bool(tmp_path):
    assert config.Ephemeral().recruitment_launch_ready is False
    (tmp_path / 'shantytown.toml').write_text('[ephemeral]\nrecruitment_launch_ready = true\n')
    assert config.load(tmp_path).ephemeral.recruitment_launch_ready is True
    (tmp_path / 'shantytown.toml').write_text('[ephemeral]\nrecruitment_launch_ready = 1\n')
    with pytest.raises(config.ConfigError, match='recruitment_launch_ready'):
        config.load(tmp_path)
