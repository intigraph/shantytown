"""Worker reservations remain bounded; canonical administrator launches are exempt."""
from dataclasses import replace

import pytest

from shantytown import cli, fleet_governor as fg
from test_fleet_governor import agent, fleet_setup, sample


def setup(tmp_path, monkeypatch, *, cap=3, peer=None):
    args = fleet_setup(tmp_path, monkeypatch, peer or sample(
        cap=cap, agents=[agent('desktop', 'remote')]))
    args.despite_hold = True
    registry = cli._registry(args)
    worker = registry.get('local')
    admin = replace(worker, name='admin', pane='admin-pane', role='administrator',
                    reports_to=None)
    registry.set(admin)
    rows = [agent('laptop', 'local')]
    monkeypatch.setattr(cli, '_governor_agents', lambda a: list(rows))
    return args, registry, worker, admin, rows


def test_worker_cannot_take_repair_slot_but_admin_can(tmp_path, monkeypatch):
    args, registry, worker, admin, rows = setup(tmp_path, monkeypatch)
    extra = replace(worker, name='extra', pane='extra-pane')
    registry.set(extra)
    refusal = cli._account_launch_refusal(args, extra)
    assert 'reserved for offline administrators' in refusal
    assert '--despite-hold does not override account capacity' in refusal
    assert cli._account_launch_refusal(args, admin) == ''
    rows.append(agent('laptop', 'admin'))
    assert '4/3' in cli._account_launch_refusal(args, extra)
    assert cli._account_launch_refusal(args, admin) == ''
    # Administrator replacement is also exempt; live accounting stays unchanged.
    assert cli._account_launch_refusal(args, admin, replacing=True) == ''


def test_worker_below_reservation_and_live_admin_are_positive_controls(tmp_path, monkeypatch):
    args, registry, worker, admin, rows = setup(tmp_path, monkeypatch, cap=4)
    assert cli._account_launch_refusal(args, worker) == ''
    # A live administrator occupies its reserved capacity, rather than adding
    # another reservation on top of that live process.
    rows[:] = [agent('laptop', 'admin')]
    assert cli._account_launch_refusal(args, worker) == ''


@pytest.mark.parametrize('change', [dict(retired=True), dict(host='outside')])
def test_unrelated_administrators_do_not_reserve_this_lane(tmp_path, monkeypatch, change):
    args, registry, worker, admin, rows = setup(tmp_path, monkeypatch)
    registry.set(replace(admin, **change))
    assert cli._account_launch_refusal(args, worker) == ''


def test_reserves_canonical_administrators_on_both_hosts(tmp_path, monkeypatch):
    args, registry, worker, admin, rows = setup(tmp_path, monkeypatch, cap=4)
    registry.set(replace(admin, name='peer-admin', host='desktop'))
    assert '2 slot(s) reserved' in cli._account_launch_refusal(args, worker)
    assert cli._account_launch_refusal(args, admin) == ''
    rows.append(agent('laptop', 'admin'))
    assert '1 slot(s) reserved' in cli._account_launch_refusal(args, worker)


def test_untrusted_peer_role_claim_cannot_spend_reserved_capacity(tmp_path, monkeypatch):
    args, registry, worker, admin, rows = setup(tmp_path, monkeypatch)
    rows[0]['role'] = 'administrator'
    assert 'reserved' in cli._account_launch_refusal(args, worker)


def test_admin_exempts_unknown_while_worker_despite_hold_does_not(tmp_path, monkeypatch):
    args, registry, worker, admin, rows = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(fg, 'collect', lambda peers: [(None, 'peer unavailable')])
    assert cli._account_launch_refusal(args, admin) == ''
    assert 'UNKNOWN' in cli._account_launch_refusal(args, worker)


def test_administrator_at_hard_cap_is_exempt_worker_refusal_remains_actionable(tmp_path, monkeypatch):
    args, registry, worker, admin, rows = setup(tmp_path, monkeypatch, cap=2)
    assert cli._account_launch_refusal(args, admin) == ''
    refusal = cli._account_launch_refusal(args, worker)
    assert '3/2' in refusal
    assert 'stop an agent in this account to free a slot' in refusal


def test_worker_refusal_precedes_workspace_mutation(tmp_path, monkeypatch, capsys):
    args, registry, worker, admin, rows = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, '_window_launch_gate', lambda a: None)
    monkeypatch.setattr(cli, '_refresh_clone', lambda *a, **k: pytest.fail('workspace mutation'))
    assert cli._launch_admitted(args, worker, None, None, dry_run=True) == cli.REFUSED
    assert 'reserved' in capsys.readouterr().err


def named_setup(tmp_path, monkeypatch):
    from shantytown import accounts, account_auth, config, governor as gov
    from test_accounts import raw
    args, registry, worker, admin, rows = setup(tmp_path, monkeypatch)
    cfg = config.Config(accounts=accounts.parse({'primary': raw(pct=20, cap=3)}))
    account = cfg.accounts['primary']
    governor = gov.Governor(account.governor, accounts.reader_for(account))
    monkeypatch.setattr(config, 'load', lambda root: cfg)
    monkeypatch.setattr(cli, '_governors', lambda a: (cfg, {'primary': governor}))
    monkeypatch.setattr(account_auth, 'available', lambda *a: True)
    worker = replace(worker, account='primary')
    admin = replace(admin, account='primary')
    registry.set(worker)
    registry.set(admin)
    rows[:] = [dict(agent('laptop', 'local'), account='primary'),
               dict(agent('laptop', 'second'), account='primary')]
    return args, worker, admin, governor


def test_named_account_reserves_admin_and_keeps_the_total_cap(tmp_path, monkeypatch):
    args, worker, admin, governor = named_setup(tmp_path, monkeypatch)
    assert 'reserved' in cli._account_launch_refusal(args, worker)
    assert cli._account_launch_refusal(args, admin) == ''


@pytest.mark.parametrize('mode', ['frozen', 'drain'])
def test_named_admin_exempts_freeze_or_full_stop_but_worker_cannot(tmp_path, monkeypatch, mode):
    from shantytown import governor as gov
    args, worker, admin, governor = named_setup(tmp_path, monkeypatch)
    verdict = governor.evaluate(persist=False)
    verdict = replace(verdict, frozen=True, why='fixture freeze') if mode == 'frozen' else replace(
        verdict, engaged=(gov.Tier(at=0, action='drain'),))
    monkeypatch.setattr(governor, 'evaluate', lambda **k: verdict)
    assert cli._account_launch_refusal(args, admin) == ''
    refusal = cli._account_launch_refusal(args, worker)
    assert refusal and 'no account-governor override' in refusal


def test_different_harness_sharing_base_account_still_reserves_capacity(tmp_path, monkeypatch):
    args, registry, worker, admin, rows = setup(tmp_path, monkeypatch)
    registry.set(replace(admin, harness='codex'))
    assert 'reserved' in cli._account_launch_refusal(args, worker)
