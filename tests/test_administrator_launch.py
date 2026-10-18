"""Administrator availability is role policy, not an account-count disguise."""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from shantytown import cli, config, fleet_governor as fg, gaming, tend
from shantytown.protocols import Agent
from shantytown.files import FilesRegistry
from shantytown.tmux import NullPanes


@pytest.fixture
def roster(tmp_path, monkeypatch):
    reg = FilesRegistry(tmp_path / 'crew')
    admin = Agent('operator', role='administrator', pane='p-operator', harness='codex')
    worker = Agent('sattler', role='worker', pane='p-worker', harness='codex')
    reg.set(admin)
    reg.set(worker)
    monkeypatch.setattr(cli, '_registry', lambda a: reg)
    return SimpleNamespace(root=tmp_path), reg, admin, worker


@pytest.mark.parametrize('cmd', ['new', 'cycle', 'start'])
def test_ordinary_admin_command_passes_gaming_worker_still_refuses(roster, monkeypatch, cmd):
    a, reg, admin, worker = roster
    gaming.manual(a.root)
    calls = []
    monkeypatch.setattr(cli, '_cmd_' + cmd, lambda a: calls.append(a.agent) or 0)
    monkeypatch.setattr(cli, '_start_roster', lambda a, c, agents:
                        (a.agent, 'explicit', [], None))
    for card in [admin, worker]:
        a.cmd, a.agent = cmd, ([card.name] if cmd == 'start' else card.name)
        assert cli._run_command(a) == (cli.OK if card is admin else cli.REFUSED)
    assert len(calls) == 1


@pytest.mark.parametrize('role', ['worker', 'lead'])
def test_name_and_forged_card_do_not_elevate(roster, role):
    a, reg, admin, worker = roster
    reg.set(replace(admin, role=role))
    assert not cli._administrator_launch(a, admin)
    assert not cli._administrator_launch(a, replace(worker, role='administrator'))


def test_retired_remote_and_unreadable_roles_not_exempt(roster, monkeypatch):
    a, reg, admin, worker = roster
    for card in [replace(admin, retired=True), replace(admin, host='other-host')]:
        reg.set(card)
        assert not cli._administrator_launch(a, card)
    monkeypatch.setattr(cli, '_registry', Mock(side_effect=OSError('unavailable')))
    assert not cli._administrator_launch(a, admin)


@pytest.mark.parametrize('problem', ['peer unreachable', 'stale census', 'missing usage',
                                    'policy disagreement'])
def test_admin_does_not_require_worker_policy_read(roster, monkeypatch, problem):
    a, reg, admin, worker = roster
    monkeypatch.setattr(cli, '_governors', Mock(side_effect=RuntimeError(problem)))
    assert cli._account_launch_refusal(a, admin) == ''
    assert 'cannot establish admission' in cli._account_launch_refusal(a, worker)


@pytest.mark.parametrize('frozen,drains,cap', [(True, (), 12), (False, ('drain',), 12),
                                             (False, (), 12), (True, ('drain',), 0)])
def test_admin_exempt_full_account_stop_and_drain_but_accounting_unchanged(
        roster, monkeypatch, frozen, drains, cap):
    a, reg, admin, worker = roster
    rows = [dict(name=f'w{i}', host='local', live=True, harness='codex') for i in range(12)]
    verdict = SimpleNamespace(frozen=frozen, drains=drains, max_agents=cap,
                              alarm='FULL STOP' if frozen else '', why='drain',
                              excludes=lambda *args: '')
    fleet = SimpleNamespace(local='local', lane=lambda lane: lane,
                            admits_launch=lambda *args, **kw:
                            'FULL STOP' if frozen or drains else
                            fg.launch_capacity_refusal('codex', cap, rows))
    def governors(args):
        args._account_governor = fleet
        return config.Config(), {'codex': SimpleNamespace(evaluate=lambda **kw: verdict)}
    monkeypatch.setattr(cli, '_governors', governors)
    monkeypatch.setattr(cli, '_governor_agents', lambda a: rows)
    monkeypatch.setattr(cli, '_administrator_launch_slots', lambda *args: {('local', admin.name)})
    assert cli._account_launch_refusal(a, admin) == ''
    assert cli._account_launch_refusal(a, worker)
    assert len(rows) == 12 and all(r['live'] for r in rows)


def test_exemption_keeps_named_credential_failure(roster, monkeypatch):
    from shantytown import accounts, account_auth
    a, reg, admin, worker = roster
    monkeypatch.setattr(accounts, 'selected', lambda *args: object())
    monkeypatch.setattr(account_auth, 'available', lambda *args: False)
    assert 'credential' in cli._account_launch_refusal(a, admin)


def test_admin_lock_is_local_even_when_peer_authority_is_down(roster, monkeypatch):
    a, reg, admin, worker = roster
    calls = []
    monkeypatch.setattr(fg, 'admission_lock', lambda *args, **kw: calls.append((args, kw)))
    cfg = SimpleNamespace(host_name='here', host_peers={'peer': object()},
                          host_admission_owner='peer', accounts={})
    cli._launch_admission_lock(a, admin, cfg)
    cli._launch_admission_lock(a, worker, cfg)
    assert calls[0] == ((a.root, None, {}), {'local_required': True})
    assert calls[1][0][2] == cfg.host_peers and calls[1][1]['owner'] == 'peer'


def test_local_admin_launch_lock_prevents_concurrent_entry(roster):
    import subprocess, sys
    a, reg, admin, worker = roster
    cfg = config.Config()
    # Independent flock acquisition proves serialization; no session is launched.
    code = ('import fcntl,sys; f=open(sys.argv[1],"a"); '
            'fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)')
    with cli._launch_admission_lock(a, admin, cfg):
        p = subprocess.run([sys.executable, '-c', code,
                            str(a.root / 'governor/admission.lock')], capture_output=True)
        assert p.returncode != 0 and b'BlockingIOError' in p.stderr
    p = subprocess.run([sys.executable, '-c', code,
                        str(a.root / 'governor/admission.lock')], capture_output=True)
    assert p.returncode == 0


def test_tend_target_exempts_only_verified_admin_and_counts_live_admin(roster):
    a, reg, admin, worker = roster
    runtime = SimpleNamespace(name='fake')
    tender = tend.Tender(NullPanes(live=set()), runtime, None, target=0,
                         codex_block=lambda c: None,
                         target_exempt=lambda c: cli._administrator_launch(a, c))
    report = tender.pass_over([admin, worker], dry_run=True)
    by_name = {f.agent: f for f in report.findings}
    assert by_name[admin.name].verdict != tend.BELOW_TARGET
    assert by_name[worker.name].verdict == tend.BELOW_TARGET
    # A live admin remains an occupied slot in a worker-only phase.
    tender = tend.Tender(NullPanes(live={admin.pane}), runtime, None, target=1,
                         codex_block=lambda c: None)
    report = tender.pass_over([worker], budget_agents=[admin, worker], dry_run=True)
    assert report.findings[0].verdict == tend.BELOW_TARGET


def test_shared_launcher_combined_gaming_and_full_account(roster, monkeypatch, capsys):
    a, reg, admin, worker = roster
    gaming.manual(a.root)
    # Reaching this provider must remain an actual error, never hidden as quota.
    runtime = SimpleNamespace(compose=lambda c: 'fixture command')
    monkeypatch.setattr(cli, '_window_launch_gate', lambda a: None)
    monkeypatch.setattr(cli, '_governors', Mock(side_effect=RuntimeError('full/unknown')))
    assert cli._launch(a, admin, NullPanes(live=set()), runtime, dry_run=True) == cli.OK
    assert cli._launch(a, worker, NullPanes(live=set()), runtime, dry_run=True) == cli.REFUSED
    output = capsys.readouterr()
    assert 'accounting unchanged' in output.err
    assert 'would launch in p-operator' in output.out
    runtime.compose = Mock(side_effect=OSError('provider unavailable'))
    assert cli._launch(a, admin, NullPanes(live=set()), runtime, dry_run=True) == cli.REFUSED


def test_tend_recovers_admin_while_worker_peer_authority_unavailable(tmp_path, monkeypatch, capsys):
    import contextlib
    from test_tend import _Args, _Panes, _roster
    root = _roster(tmp_path, {'operator': {'role': 'administrator', 'pane': 'p-admin'},
                              'worker': {'role': 'worker', 'pane': 'p-worker'}})
    (root / 'shantytown.toml').write_text(
        '[host]\nname="desktop"\nadmission_owner="peer"\n'
        '[host.peers.peer]\nssh="user@example.test"\nroot="/fixture"\n')
    gaming.manual(root)
    monkeypatch.setattr(cli, 'Tmux', lambda *args, **kw: _Panes(live=set()))
    monkeypatch.setattr(fg, 'collect', lambda peers: [(None, 'peer unreachable')])
    original = fg.admission_lock
    @contextlib.contextmanager
    def lock(root, host, peers, **kw):
        if peers:
            raise fg.AdmissionUnavailable('peer unavailable')
        with original(root, host, peers, **kw):
            yield
    monkeypatch.setattr(fg, 'admission_lock', lock)
    assert cli._tend_once(_Args(root, dry_run=True)) == cli.CANNOT_TELL
    output = capsys.readouterr()
    assert 'would-respawn' in output.out and 'operator' in output.out
    assert 'peer unavailable' in output.err
    assert not list((root / 'governor').glob('state*.json'))


def test_exempt_admin_still_cannot_clobber_existing_session(roster, monkeypatch):
    a, reg, admin, worker = roster
    admin = replace(admin, harness='claude')
    reg.set(admin)
    gaming.manual(a.root)
    monkeypatch.setattr(cli, '_window_launch_gate', lambda a: None)
    monkeypatch.setattr(cli, 'ensure_workspace', lambda card: None)
    monkeypatch.setattr(cli, 'provision_ws', lambda *args, **kw: [])
    runtime = SimpleNamespace(compose=lambda c: 'fixture', start=Mock())
    panes = NullPanes(live={admin.pane})
    assert cli._launch(a, admin, panes, runtime) == cli.REFUSED
    assert panes.exists(admin.pane)
    runtime.start.assert_not_called()


def test_harness_conversion_ignores_governor_only_for_admin(roster, monkeypatch):
    a, reg, admin, worker = roster
    monkeypatch.setattr(cli, '_harness_lane_held', lambda *args: True)
    for card in [admin, worker]:
        args = SimpleNamespace(root=a.root, agent=card.name, target='claude',
                               model='fixture-model', now=True, force=False, dry_run=True)
        assert cli._cmd_harness(args) == (cli.OK if card is admin else cli.REFUSED)


def test_cycle_uses_same_local_admin_lock_before_replacement(roster, monkeypatch):
    from shantytown import cycle
    a, reg, admin, worker = roster
    reached = []
    def restart(args, card, *unused):
        assert args._cycle_admission_locked
        assert (a.root / 'governor/admission.lock').exists()
        reached.append(card.name)
        return cli.OK, cycle.RESPAWN
    monkeypatch.setattr(cli, '_restart_cycle', restart)
    chosen = cycle.Plan(cycle.RESPAWN, 'fixture')
    assert cli._perform_cycle_locked(a, admin, admin.name, admin.pane,
                                     None, None, chosen, None)[0] == cli.OK
    assert reached == [admin.name]
    assert not hasattr(a, '_cycle_admission_locked')


def test_routine_drain_cannot_immediately_undo_admin_recovery(roster, monkeypatch):
    from shantytown.inbox import FilesInbox
    from test_governor_drain_expiry import _verdict
    a, reg, admin, worker = roster
    inbox = FilesInbox(a.root / 'inbox')
    monkeypatch.setattr(cli, '_inbox', lambda *args, **kw: inbox)
    monkeypatch.setattr(cli, '_me', lambda a: 'fixture')
    monkeypatch.setattr(cli, '_catalog', lambda a: None)
    verdict = _verdict(a.root, 99)
    panes = NullPanes(live={admin.pane, worker.pane})
    cli._drain_sweep(a, verdict, [admin, worker], panes, episode=1)
    assert inbox.unread(admin.name) == []
    assert len(inbox.unread(worker.name)) == 1
    # A worker promoted in the canonical registry loses its old routine drain.
    promoted = replace(worker, role='administrator')
    reg.set(promoted)
    cli._drain_sweep(a, verdict, [admin, promoted], panes, episode=1)
    assert inbox.unread(promoted.name) == []
