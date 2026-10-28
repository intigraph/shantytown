"""Probe freshness is independent of receiving host and transport arrival time."""
import pytest

from shantytown.fleet_governor import FreshestReader
from shantytown.governor import GovernorError, Reading


def test_selects_each_windows_freshest_producer_observation():
    first = {'five_hour': Reading(pct=20, at=100),
             'seven_day': Reading(pct=30, at=200)}
    second = {'five_hour': Reading(pct=80, at=200),
              'seven_day': Reading(pct=90, at=100)}
    reader = FreshestReader({'desktop': first, 'laptop': second})
    assert reader.read_all() == {'five_hour': second['five_hour'],
                                 'seven_day': first['seven_day']}
    assert reader.provenance == {'five_hour': 'laptop', 'seven_day': 'desktop'}


def test_new_failure_cannot_be_hidden_by_older_success():
    failed = Reading(pct=12, at=200, ok=False, probe_http_status=429)
    reader = FreshestReader({'desktop': {'five_hour': Reading(pct=10, at=100)},
                             'laptop': {'five_hour': failed}})
    assert reader.read_all()['five_hour'] == failed
    assert reader.read_all()['five_hour'].lost(now=201, max_age=300)


def test_ties_have_same_provenance_from_either_host():
    first = {'five_hour': Reading(pct=20, at=100)}
    second = {'five_hour': Reading(pct=40, at=100)}
    one = FreshestReader({'desktop': first, 'laptop': second})
    two = FreshestReader({'laptop': second, 'desktop': first})
    assert one.read_all() == two.read_all()
    assert one.provenance == two.provenance == {'five_hour': 'desktop'}


def test_undated_observation_does_not_supplant_dated_one():
    dated = Reading(pct=80, at=100)
    reader = FreshestReader({'desktop': {'five_hour': Reading(pct=10)},
                             'laptop': {'five_hour': dated}})
    assert reader.read_all()['five_hour'] == dated
    unaged = FreshestReader({'desktop': {'five_hour': Reading(pct=10)}})
    assert unaged.read_all()['five_hour'].at is None
    assert unaged.read_all()['five_hour'].lost(now=201, max_age=300)


@pytest.mark.parametrize('stamp', [float('nan'), float('inf'), True, '200'])
def test_invalid_timestamp_refuses_instead_of_winning_freshness(stamp):
    with pytest.raises(GovernorError):
        FreshestReader({'desktop': {'five_hour': Reading(pct=10, at=stamp)}})


def test_retains_cache_age_and_does_not_refresh_stale_data_on_read():
    observation = Reading(pct=10, at=100, cache_age=5000)
    reader = FreshestReader({'desktop': {'five_hour': observation}})
    assert reader.read_all()['five_hour'] == observation
    assert reader.read_all()['five_hour'].lost(now=101, max_age=300)
    returned = reader.read_all()
    returned.clear()
    assert reader.read_all()['five_hour'] == observation


from dataclasses import replace
import json
from types import SimpleNamespace
from shantytown import cli, fleet_governor as fg, governor as gov
from shantytown.config import HostPeer
from pathlib import Path
from test_crew_work import _Args, _Panes, _roster, IDLE_SCREEN


def agent(host, name, harness='claude', live=True):
    return dict(host=host, name=name, harness=harness, live=live)


def sample(host='desktop', cap=2, pct=10, at=None, agents=None):
    import time
    at = time.time() if at is None else at
    policy = gov.Policy(tiers=(gov.Tier(at=50, min_priority=1),), max_agents=cap)
    reader = FreshestReader({host: {'five_hour': Reading(pct=pct, at=at)}})
    return fg.snapshot(host, {'base': gov.Governor(policy, reader)}, agents or [], now=at, hosts=['desktop', 'laptop'], admission_owner='desktop')


def test_roundtrip_portable_policy_omits_reader_coordinates_and_credentials():
    policy = gov.parse({'source': 'prometheus', 'url': 'https://secret.example.test',
                        'username': 'private-user', 'password_file': '/private/token',
                        'tier': [{'at': 50, 'traits': ['support']}],
                        'burndown': [{'window': 'five_hour', 'within': 900}],
                        'pace': [{'window': 'five_hour', 'ratio': 1.1}]})
    encoded = json.dumps(fg.policy_wire(policy))
    assert 'secret' not in encoded and 'private' not in encoded
    portable = gov.parse(json.loads(encoded))
    assert portable.tiers == policy.tiers
    assert portable.burndowns == policy.burndowns and portable.paces == policy.paces
    assert portable.url is None and portable.password_file is None


def test_peer_policy_governs_host_with_no_local_policy_and_counts_both(tmp_path):
    local = fg.snapshot('laptop', {}, [agent('laptop', 'local')], admission_owner='desktop')
    peer = sample(agents=[agent('desktop', 'remote')])
    fleet = fg.FleetGovernor(local, [(peer, '')], tmp_path)
    assert fleet.policy_hosts == {'base': 'desktop'}
    assert fleet.counts() == {'base': 2}
    assert '3/2' in fleet.admits_launch('claude')
    assert fleet.admits_launch('claude', []) == ''


def test_both_hosts_derive_same_freshest_verdict_and_hysteresis(tmp_path):
    first = sample(at=1000, pct=51)
    second = sample('laptop', at=1001, pct=49)
    first['governors']['base']['state'] = dict(at=50, since=990, by_window={})
    a = fg.FleetGovernor(first, [(second, '')], tmp_path / 'a')
    b = fg.FleetGovernor(second, [(first, '')], tmp_path / 'b')
    for fleet in (a, b):
        fleet.governors['base']._now = lambda: 1002
    va = a.governors['base'].evaluate(persist=False)
    vb = b.governors['base'].evaluate(persist=False)
    assert va == vb
    assert va.pct == 49 and va.held and va.floor == 1


def test_failed_peer_holds_growth_but_retains_local_reading(tmp_path):
    fleet = fg.FleetGovernor(sample(), [(None, 'laptop governor unavailable')], tmp_path)
    assert fleet.governors['base'].evaluate(persist=False).pct == 10
    assert 'peer occupancy or agreement UNKNOWN' in fleet.admits_launch('claude')
    assert 'fallback' in fleet.fallback()


def test_disagreeing_policy_cannot_silently_choose_larger_cap(tmp_path):
    fleet = fg.FleetGovernor(sample(cap=8), [(sample('laptop', cap=2), '')], tmp_path)
    assert 'policies disagree' in fleet.admits_launch('claude')


@pytest.mark.parametrize('mutate', [
    lambda s: s.update(observed_at=0),
    lambda s: s.update(scope='fleet'),
    lambda s: s.update(complete=False),
    lambda s: s['governors']['base']['readings']['five_hour'].update(pct=float('nan')),
    lambda s: s['governors']['base']['readings']['five_hour'].update(ok=1),
    lambda s: s['governors']['base']['policy'].update(password_file='/private/token'),
    lambda s: s['agents'].append(agent('wrong-host', 'intruder')),
])
def test_invalid_peer_envelopes_refuse(mutate):
    data = sample()
    mutate(data)
    with pytest.raises((ValueError, TypeError, GovernorError)):
        fg.validate(data, 'desktop')


def test_peer_transport_is_bounded_local_and_does_not_leak_stderr(monkeypatch):
    peer = HostPeer('desktop', 'user@example.test', '/tmp/a b')
    def run(argv, **kw):
        assert kw['timeout'] == 20
        assert "--root '/tmp/a b' crew --governor --json --local" in argv[-1]
        return SimpleNamespace(returncode=0, stdout=json.dumps(sample()), stderr='')
    monkeypatch.setattr(fg.subprocess, 'run', run)
    result, error = fg.read_peer(peer)
    assert result['host'] == 'desktop' and not error
    monkeypatch.setattr(fg.subprocess, 'run', lambda *a, **k:
                        SimpleNamespace(returncode=1, stdout='', stderr='credential-secret'))
    result, error = fg.read_peer(peer)
    assert result is None and 'remote st exit 1' in error and 'secret' not in error


def fleet_setup(tmp_path, monkeypatch, peer=None):
    root = _roster(tmp_path, {'local': 'local-pane'})
    (root / 'shantytown.toml').write_text(
        '[host]\nname="laptop"\nadmission_owner="desktop"\n[host.peers.desktop]\nssh="user@example.test"\nroot="/tmp/root"\n')
    monkeypatch.setattr(cli, 'Tmux', lambda *a, **k: _Panes({'local-pane': IDLE_SCREEN}))
    monkeypatch.setattr(fg, 'collect', lambda peers: [(peer or sample(
        agents=[agent('desktop', 'remote')]), '')])
    return _Args(root)


def test_local_json_is_nonrecursive_and_peerless_policy_is_not_off(tmp_path, monkeypatch, capsys):
    args = fleet_setup(tmp_path, monkeypatch)
    args.governor = args.json = args.local = True
    monkeypatch.setattr(fg, 'collect', lambda p: pytest.fail('recursive governor poll'))
    assert cli._cmd_crew(args) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['scope'] == 'local' and output['governors'] == {}
    fg.validate(output, 'laptop')


def test_fleet_json_and_human_display_show_remote_agents_and_policy(tmp_path, monkeypatch, capsys):
    args = fleet_setup(tmp_path, monkeypatch)
    args.governor = args.json = True
    assert cli._cmd_crew(args) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['governors']['base']['live'] == 2
    assert output['governors']['base']['policy_host'] == 'desktop'
    args.json = False
    assert cli._cmd_crew(args) == 0
    output = capsys.readouterr().out
    assert 'desktop remote claude live' in output
    assert 'laptop local claude live' in output
    assert 'live 2/2' in output


def test_launch_refusal_precedes_daemon_repair_and_workspace_mutation(tmp_path, monkeypatch, capsys):
    args = fleet_setup(tmp_path, monkeypatch)
    card = cli._registry(args).all().exact()[0]
    monkeypatch.setattr(cli, '_window_launch_gate', lambda a: None)
    monkeypatch.setattr(cli, '_refresh_clone', lambda *a, **k: pytest.fail('mutated workspace'))
    assert cli._launch_admitted(args, card, None, None, dry_run=True) == cli.REFUSED
    assert '3/2' in capsys.readouterr().err


def test_account_admission_recounts_local_launches_in_same_tend_pass(tmp_path, monkeypatch):
    args = fleet_setup(tmp_path, monkeypatch, sample(cap=3, agents=[agent('desktop', 'remote')]))
    card = cli._registry(args).all().exact()[0]
    assert cli._account_launch_refusal(args, card) == ''
    monkeypatch.setattr(cli, '_governor_agents', lambda a: [
        agent('laptop', 'local'), agent('laptop', 'just-launched')])
    assert '4/3' in cli._account_launch_refusal(args, card)


def test_invalid_peer_census_is_advisory_for_dispatch(tmp_path, monkeypatch, capsys):
    """aegis-lfeg: a peer's bad census never holds this host's own dispatch."""
    args = fleet_setup(tmp_path, monkeypatch)
    monkeypatch.setattr(fg, 'collect', lambda _: [(None, 'desktop governor unavailable')])
    gate = cli._dispatch_gate(args)
    assert gate is None or not gate(None, 'local')
    err = capsys.readouterr().err
    assert err.count('\n') == 1 and 'desktop census invalid (never seen)' in err


def test_local_admission_lock_excludes_another_process(tmp_path):
    import subprocess
    import sys
    peer = HostPeer('laptop', 'unused', '/unused')
    script = '''import fcntl, pathlib, sys
with (pathlib.Path(sys.argv[1]) / 'governor' / 'admission.lock').open('a') as f:
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit(7)
'''
    with fg.admission_lock(tmp_path, 'desktop', {'laptop': peer}, owner='desktop'):
        result = subprocess.run([sys.executable, '-c', script, str(tmp_path)])
        assert result.returncode == 7
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path)])
    assert result.returncode == 0


def test_tend_entrypoint_holds_down_agent_at_remote_cap(tmp_path, monkeypatch, capsys):
    from test_tend import _Args as TendArgs, _Panes as TendPanes, _roster as tend_roster
    root = tend_roster(tmp_path, {'local': {'role': 'worker', 'pane': 'local-pane'}})
    (root / 'shantytown.toml').write_text(
        '[host]\nname="desktop"\nadmission_owner="desktop"\n[host.peers.laptop]\nssh="user@example.test"\nroot="/tmp/root"\n')
    panes = TendPanes(live=set())
    monkeypatch.setattr(cli, 'Tmux', lambda *a, **k: panes)
    monkeypatch.setattr(fg, 'collect', lambda _: [(sample('laptop', cap=1,
        agents=[agent('laptop', 'remote')]), '')])
    args = TendArgs(root, dry_run=True)
    assert cli._tend_once(args) == cli.OK
    output = capsys.readouterr().out
    assert '2/1' in output and 'governed' in output
    assert 'would-respawn' not in output
    assert not list((root / 'governor').glob('state*.json'))


@pytest.mark.parametrize('owner', ['desktop', 'z-server'])
def test_remote_lock_uses_same_authority_file_and_releases_on_exception(tmp_path, monkeypatch, owner):
    import subprocess
    import fcntl
    original = subprocess.Popen
    def launch(argv, **kw):
        assert argv[0] == 'ssh' and argv[-2] == 'user@example.test'
        return original(['/bin/sh', '-c', argv[-1]], **kw)
    monkeypatch.setattr(fg.subprocess, 'Popen', launch)
    peer = HostPeer(owner, 'user@example.test', str(tmp_path))
    with pytest.raises(RuntimeError, match='caller failed'):
        with fg.admission_lock('/unused', 'laptop', {owner: peer}, owner=owner):
            with (tmp_path / 'governor' / 'admission.lock').open('a') as handle:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            raise RuntimeError('caller failed')
    with (tmp_path / 'governor' / 'admission.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _lock_is_held(root):
    """flock conflicts across open file descriptions, even within one process."""
    import fcntl
    with (Path(root) / 'governor' / 'admission.lock').open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(handle, fcntl.LOCK_UN)
        return False


def test_reachable_authority_keeps_the_single_owner_lock(tmp_path, monkeypatch):
    import subprocess
    original = subprocess.Popen
    monkeypatch.setattr(fg.subprocess, 'Popen',
                        lambda argv, **kw: original(['/bin/sh', '-c', argv[-1]], **kw))
    remote, local = tmp_path / 'remote', tmp_path / 'local'
    peer = HostPeer('desktop', 'user@example.test', str(remote))
    with fg.admission_lock(local, 'laptop', {'desktop': peer}, owner='desktop') as admission:
        assert admission == fg.Admission(lock_host='desktop', owner='desktop')
        assert _lock_is_held(remote)
    assert not (local / 'governor' / 'admission.lock').exists()
    assert fg.degraded_admission_line(admission, None) == ''


@pytest.mark.parametrize('failure', ['oserror', 'ssh-255', 'no-python'])
def test_unreachable_authority_degrades_to_this_hosts_lock(tmp_path, monkeypatch, failure):
    import subprocess
    original = subprocess.Popen
    def launch(argv, **kw):
        if failure == 'oserror':
            raise OSError('no ssh')
        return original(['/bin/sh', '-c', 'exit 255' if failure == 'ssh-255' else 'exit 127'], **kw)
    monkeypatch.setattr(fg.subprocess, 'Popen', launch)
    peer = HostPeer('desktop', 'user@example.test', '/remote')
    with fg.admission_lock(tmp_path, 'laptop', {'desktop': peer}, owner='desktop') as admission:
        assert admission == fg.Admission(lock_host='laptop', owner='desktop', unreachable='desktop')
        # Still serialized: another local launch cannot interleave.
        assert _lock_is_held(tmp_path)
    assert not _lock_is_held(tmp_path)


def test_busy_reachable_authority_still_refuses(tmp_path, monkeypatch):
    import subprocess
    original = subprocess.Popen
    monkeypatch.setattr(fg.subprocess, 'Popen', lambda argv, **kw: original(
        ['/bin/sh', '-c', f'exit {fg.REMOTE_LOCK_BUSY}'], **kw))
    peer = HostPeer('desktop', 'user@example.test', '/remote')
    with pytest.raises(fg.AdmissionUnavailable, match='busy'):
        with fg.admission_lock(tmp_path, 'laptop', {'desktop': peer}, owner='desktop'):
            pytest.fail('admitted while the authority was busy')
    assert not (tmp_path / 'governor' / 'admission.lock').exists()


def _owner_helper(monkeypatch, script, root='/remote'):
    import subprocess
    original = subprocess.Popen
    monkeypatch.setattr(fg.subprocess, 'Popen', lambda argv, **kw: original(
        ['/bin/sh', '-c', script.replace('{HELPER}', argv[-1])], **kw))
    return HostPeer('desktop', 'user@example.test', root)


def test_slow_connect_busy_owner_is_busy_not_unreachable(tmp_path, monkeypatch):
    """SSH connect+auth delays the helper's own 10s wait past ours; when it then
    exits BUSY, the owner is up and locked by another launch: refuse, never
    admit locally (review follow-up on #396)."""
    monkeypatch.setattr(fg, 'REMOTE_LOCK_READY_S', .2)
    monkeypatch.setattr(fg, 'REMOTE_LOCK_BUSY_GRACE_S', 5)
    peer = _owner_helper(monkeypatch, f'sleep .8; exit {fg.REMOTE_LOCK_BUSY}')
    with pytest.raises(fg.AdmissionUnavailable, match='busy'):
        with fg.admission_lock(tmp_path, 'laptop', {'desktop': peer}, owner='desktop'):
            pytest.fail('admitted locally while the owner was busy')
    assert not (tmp_path / 'governor' / 'admission.lock').exists()


def test_helper_hung_past_the_grace_is_unreachable(tmp_path, monkeypatch):
    monkeypatch.setattr(fg, 'REMOTE_LOCK_READY_S', .2)
    monkeypatch.setattr(fg, 'REMOTE_LOCK_BUSY_GRACE_S', .3)
    peer = _owner_helper(monkeypatch, 'exec sleep 30')
    with fg.admission_lock(tmp_path, 'laptop', {'desktop': peer}, owner='desktop') as admission:
        assert admission.unreachable == 'desktop'


def test_shell_noise_before_locked_still_takes_the_owner_lock(tmp_path, monkeypatch):
    remote = tmp_path / 'remote'
    peer = _owner_helper(monkeypatch, 'echo "Welcome to desktop"; printf "rc noise\\r\\n"; {HELPER}',
                         str(remote))
    with fg.admission_lock(tmp_path / 'local', 'laptop', {'desktop': peer},
                           owner='desktop') as admission:
        assert admission == fg.Admission(lock_host='desktop', owner='desktop')
        assert _lock_is_held(remote)
    assert not _lock_is_held(remote)


def test_noise_without_locked_is_unreachable(tmp_path, monkeypatch):
    peer = _owner_helper(monkeypatch, 'echo banner; echo "locked-ish"; exit 0')
    with fg.admission_lock(tmp_path, 'laptop', {'desktop': peer}, owner='desktop') as admission:
        assert admission.unreachable == 'desktop'


def test_asymmetric_membership_cannot_choose_two_lock_authorities(tmp_path):
    local = sample()
    peer = sample('laptop')
    peer['hosts'] = ['another', 'desktop', 'laptop']
    f = fg.FleetGovernor(local, [(peer, '')], tmp_path)
    assert 'host membership disagrees' in f.admits_launch('claude')


def test_explicit_local_owner_ignores_alphabetically_earlier_peer(tmp_path, monkeypatch):
    monkeypatch.setattr(fg.subprocess, 'Popen', lambda *a, **k: pytest.fail('contacted sleeping peer'))
    peer = HostPeer('a-laptop', 'unused', '/unused')
    with fg.admission_lock(tmp_path, 'z-server', {'a-laptop': peer}, owner='z-server'):
        assert (tmp_path / 'governor' / 'admission.lock').is_file()


def test_undeclared_owner_is_still_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(fg.subprocess, 'Popen', lambda *a, **k: pytest.fail('contacted peer'))
    peer = HostPeer('laptop', 'unused', '/unused')
    with pytest.raises(fg.AdmissionUnavailable):
        with fg.admission_lock(tmp_path, 'server', {'laptop': peer}, owner='not-declared'):
            pytest.fail('admitted without a declared authority')
    assert not (tmp_path / 'governor').exists()


def test_peers_without_an_owner_admit_under_this_hosts_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(fg.subprocess, 'Popen', lambda *a, **k: pytest.fail('contacted peer'))
    peer = HostPeer('laptop', 'unused', '/unused')
    with fg.admission_lock(tmp_path, 'server', {'laptop': peer}) as admission:
        assert admission == fg.Admission(lock_host='server')
        assert _lock_is_held(tmp_path)


def test_config_with_peers_and_no_owner_loads(tmp_path):
    from shantytown import config
    (tmp_path / 'shantytown.toml').write_text(
        '[host]\nname="laptop"\n[host.peers.desktop]\nssh="user@example.test"\nroot="/r"\n')
    cfg = config.load(tmp_path)
    assert cfg.host_admission_owner is None and set(cfg.host_peers) == {'desktop'}


@pytest.mark.parametrize('host', [None, 'standalone'])
def test_single_host_needs_no_authority_configuration(tmp_path, monkeypatch, host):
    monkeypatch.setattr(fg.subprocess, 'Popen', lambda *a, **k: pytest.fail('contacted peer'))
    with fg.admission_lock(tmp_path, host, {}):
        pass


@pytest.mark.parametrize('peer_owner', [None, 'laptop'])
def test_old_or_disagreeing_peer_authority_holds_launch_and_dispatch(tmp_path, peer_owner):
    local, peer = sample(), sample('laptop')
    if peer_owner is None:
        del peer['admission_owner']  # an old binary, not an empty new config
    else:
        peer['admission_owner'] = peer_owner
    fleet = fg.FleetGovernor(local, [(peer, '')], tmp_path)
    assert 'admission authority' in fleet.admits_launch('claude')
    assert 'admission authority' in fleet.fallback()


def test_config_loads_explicit_authority(tmp_path):
    from shantytown import config
    (tmp_path / 'shantytown.toml').write_text(
        '[host]\nname="z-server"\nadmission_owner="z-server"\n'
        '[host.peers.a-laptop]\nssh="user@example.test"\nroot="/tmp/root"\n')
    assert config.load(tmp_path).host_admission_owner == 'z-server'


@pytest.mark.parametrize('owner', ['""', '42', 'false', '"unknown"'])
def test_config_rejects_invalid_authority(tmp_path, owner):
    from shantytown import config
    (tmp_path / 'shantytown.toml').write_text(
        f'[host]\nname="server"\nadmission_owner={owner}\n')
    with pytest.raises(config.ConfigError, match='admission_owner'):
        config.load(tmp_path)


def offline_fleet(tmp_path, monkeypatch, local=None, now=None):
    peers = {'laptop': HostPeer('laptop', 'user@example.test', '/remote')}
    def disconnected(*args, **kwargs):
        raise ConnectionRefusedError('peer asleep')
    monkeypatch.setattr(fg.subprocess, 'run', disconnected)
    return fg.FleetGovernor(local or sample(), fg.collect(peers), tmp_path,
                            peer_config=peers, now=now)


def cache_peer(tmp_path, peer):
    config = {'laptop': HostPeer('laptop', 'user@example.test', '/remote')}
    return fg.FleetGovernor(sample(), [(peer, '')], tmp_path, peer_config=config)


def test_unreachable_peer_counts_its_last_census(tmp_path, monkeypatch):
    import time
    now = time.time()
    cache_peer(tmp_path, sample('laptop', at=now - 600,
                               agents=[agent('laptop', 'remote')]))
    fleet = offline_fleet(tmp_path, monkeypatch, now=now)
    assert fleet.errors == []
    assert fleet.counts() == {'base': 1}
    assert fleet.admits_launch('claude') == ''
    assert '3/2' in fleet.admits_launch('claude', [agent('desktop', 'local')])
    assert fleet.warnings == ['laptop unreachable; cached count age 600s; 1 counted live']
    assert fleet.estimates == {'laptop': dict(age=600, live=1)}
    # Cached readings cannot win freshest-observation selection or get restamped.
    reader = fleet.governors['base'].reader
    assert reader.provenance == {'five_hour': 'desktop'}
    assert reader.read_all()['five_hour'].at > now - 600


@pytest.mark.parametrize('owner', [None, 'desktop', 'laptop'])
def test_offline_fallback_works_on_any_host(tmp_path, monkeypatch, owner):
    """The census fallback is not reserved for the owner: no host depends on another."""
    import time
    now = time.time()
    cached = sample('laptop', at=now - 60, agents=[agent('laptop', 'remote')])
    cached['admission_owner'] = owner
    cache_peer(tmp_path, cached)
    local = sample()
    local['admission_owner'] = owner
    fleet = offline_fleet(tmp_path, monkeypatch, local=local, now=now)
    assert fleet.errors == [] and fleet.admits_launch('claude') == ''
    assert fleet.counts() == {'base': 1}


def test_never_seen_peer_counts_zero_and_is_flagged(tmp_path, monkeypatch):
    fleet = offline_fleet(tmp_path, monkeypatch)
    assert fleet.errors == []
    assert fleet.counts() == {'base': 0}
    assert fleet.admits_launch('claude') == ''
    assert fleet.warnings == ['laptop unreachable; never seen; occupancy UNKNOWN, counted 0']
    assert fleet.estimates == {'laptop': dict(age=None, live=0)}


@pytest.mark.parametrize('disagreement', ['policy', 'hosts', 'owner'])
def test_reachable_disagreement_holds_but_remembered_one_only_warns(tmp_path, monkeypatch, disagreement):
    peer = sample('laptop', agents=[agent('laptop', 'remote')])
    if disagreement == 'policy':
        peer['governors']['base']['policy']['max_agents'] = 10
    elif disagreement == 'hosts':
        peer['hosts'] = ['laptop']
    else:
        peer['admission_owner'] = 'laptop'
    live = cache_peer(tmp_path, peer)
    assert live.errors and live.admits_launch('claude')
    offline = offline_fleet(tmp_path, monkeypatch)
    assert offline.errors == [] and offline.admits_launch('claude') == ''
    assert len(offline.warnings) == 2
    # The LOCAL policy's cap still binds the remembered occupancy.
    assert '3/2' in offline.admits_launch('claude', [agent('desktop', 'local')])


@pytest.mark.parametrize('age', [fg.PEER_CENSUS_MAX_AGE + 1, -31])
def test_stale_or_future_cache_is_advisory_only(tmp_path, monkeypatch, age):
    """aegis-lfeg: a census past the bound never holds local launches."""
    import time
    now = time.time()
    cache_peer(tmp_path, sample('laptop', at=now - age, cap=1, agents=[
        agent('laptop', 'a'), agent('laptop', 'b')]))
    local = sample()
    local['governors'] = {}
    fleet = offline_fleet(tmp_path, monkeypatch, local=local, now=now)
    assert fleet.errors == []
    # Not counted, and its policy is not borrowed: the stale cap of 1 is gone.
    assert fleet.counts() == {}
    assert fleet.admits_launch('claude') == ''
    assert fleet.estimates['laptop']['advisory'] is True
    assert 'advisory only' in fleet.warnings[0]
    assert len(fleet.warnings) == 1  # no "policy taken from the last census" line


def test_census_bound_is_configurable(tmp_path, monkeypatch):
    import time
    now = time.time()
    cache_peer(tmp_path, sample('laptop', at=now - 600, agents=[
        agent('laptop', 'a'), agent('laptop', 'b')]))
    peers = {'laptop': HostPeer('laptop', 'user@example.test', '/remote')}
    monkeypatch.setattr(fg.subprocess, 'run', lambda *a, **k: (_ for _ in ()).throw(OSError()))
    tight = fg.FleetGovernor(sample(), fg.collect(peers), tmp_path, peer_config=peers,
                             now=now, census_max_age=300)
    assert tight.counts() == {'base': 0} and tight.admits_launch('claude') == ''
    loose = fg.FleetGovernor(sample(), fg.collect(peers), tmp_path, peer_config=peers,
                             now=now, census_max_age=3600)
    assert loose.counts() == {'base': 2} and '3/2' in loose.admits_launch('claude')


def test_fresh_reachable_peer_census_still_binds(tmp_path):
    full = sample('laptop', agents=[agent('laptop', 'a'), agent('laptop', 'b')])
    peers = {'laptop': HostPeer('laptop', 'user@example.test', '/remote')}
    fleet = fg.FleetGovernor(sample(), [(full, '')], tmp_path, peer_config=peers)
    assert fleet.errors == [] and fleet.warnings == [] and fleet.notice() == ''
    assert fleet.counts() == {'base': 2}
    assert '3/2' in fleet.admits_launch('claude')


def test_notice_is_one_short_line(tmp_path, monkeypatch):
    import time
    now = time.time()
    cache_peer(tmp_path, sample('laptop', at=now - 139483, agents=[agent('laptop', 'a')]))
    fleet = offline_fleet(tmp_path, monkeypatch, now=now)
    assert fleet.notice() == ('peers: laptop unreachable (census 1d old, advisory) '
                              '(st crew --governor)')
    assert '\n' not in fleet.notice()


def test_config_census_max_age(tmp_path):
    from shantytown import config
    (tmp_path / 'shantytown.toml').write_text('[host]\nname="a"\n')
    assert config.load(tmp_path).host_peer_census_max_age == fg.PEER_CENSUS_MAX_AGE
    (tmp_path / 'shantytown.toml').write_text('[host]\nname="a"\npeer_census_max_age=60\n')
    assert config.load(tmp_path).host_peer_census_max_age == 60
    for bad in ('0', '"6h"', 'true'):
        (tmp_path / 'shantytown.toml').write_text(f'[host]\nname="a"\npeer_census_max_age={bad}\n')
        with pytest.raises(config.ConfigError, match='peer_census_max_age'):
            config.load(tmp_path)


def test_lane_only_an_unreachable_peer_declared_keeps_its_cap(tmp_path, monkeypatch):
    import time
    now = time.time()
    cache_peer(tmp_path, sample('laptop', at=now - 7200, cap=1,
                               agents=[agent('laptop', 'remote')]))
    local = sample()
    local['governors'] = {}
    fleet = offline_fleet(tmp_path, monkeypatch, local=local, now=now)
    assert fleet.errors == []
    assert fleet.policy_hosts == {'base': 'laptop'}
    # The two-hour-old reading is signal-lost; warn policy keeps the baseline cap.
    assert fleet.governors['base'].evaluate(persist=False).signal_lost
    assert '2/1' in fleet.admits_launch('claude')


@pytest.mark.parametrize('on_lost, refused', [('warn', False), ('freeze', True)])
def test_stale_local_usage_follows_the_policy_not_the_outage(tmp_path, monkeypatch, on_lost, refused):
    local = sample()
    local['governors']['base']['policy']['on_signal_lost'] = on_lost
    local['governors']['base']['readings']['five_hour'].update(at=0)
    fleet = offline_fleet(tmp_path, monkeypatch, local=local)
    assert fleet.errors == []
    assert bool(fleet.admits_launch('claude')) is refused


def test_invalid_reachable_snapshot_is_advisory_and_keeps_last_good_census(tmp_path, monkeypatch):
    """aegis-lfeg: version or clock skew on a peer never holds this host."""
    import time
    now = time.time()
    cache_peer(tmp_path, sample('laptop', at=now - 600, agents=[agent('laptop', 'remote')]))
    peers = {'laptop': HostPeer('laptop', 'user@example.test', '/remote')}
    monkeypatch.setattr(fg.subprocess, 'run', lambda *a, **k:
                        SimpleNamespace(returncode=0, stdout='not-json', stderr=''))
    results = fg.collect(peers)
    assert not isinstance(results[0][1], fg.PeerUnreachable)
    fleet = fg.FleetGovernor(sample(), results, tmp_path, peer_config=peers, now=now)
    assert fleet.errors == [] and fleet.admits_launch('claude') == ''
    assert fleet.counts() == {'base': 1}  # last good census, still within the bound
    assert 'laptop census invalid (1 counted from 10m-old census)' in fleet.notice()
    # The invalid answer did not overwrite the good cache.
    offline = offline_fleet(tmp_path, monkeypatch, now=now)
    assert offline.counts() == {'base': 1}


def test_legacy_invalid_cache_record_counts_zero(tmp_path, monkeypatch):
    peers = {'laptop': HostPeer('laptop', 'user@example.test', '/remote')}
    path = fg._peer_cache(tmp_path, peers['laptop'])
    fg._save_peer(path, None, 'laptop governor unavailable')
    offline = offline_fleet(tmp_path, monkeypatch)
    assert offline.admits_launch('claude') == ''
    assert 'last reachable census was invalid' in offline.warnings[0]
    assert 'counted 0' in offline.warnings[0]


def test_corrupt_cache_is_flagged_not_mistaken_for_never_seen(tmp_path, monkeypatch):
    cache_peer(tmp_path, sample('laptop'))
    next((tmp_path / 'governor' / 'peers').glob('*.json')).write_text('broken')
    fleet = offline_fleet(tmp_path, monkeypatch)
    assert fleet.admits_launch('claude') == ''
    assert 'cached census unusable' in fleet.warnings[0]


def test_ssh_and_remote_st_failures_are_both_unreachable(monkeypatch):
    peer = HostPeer('laptop', 'user@example.test', '/remote')
    for code, text in ((255, 'SSH transport failed'), (1, 'remote st exit 1'),
                       (127, 'remote st exit 127')):
        monkeypatch.setattr(fg.subprocess, 'run', lambda *a, **k:
                            SimpleNamespace(returncode=code, stdout='', stderr='secret'))
        _, error = fg.read_peer(peer)
        assert isinstance(error, fg.PeerUnreachable) and text in error
        assert 'secret' not in error


def test_degraded_admission_line_names_every_unseen_host():
    fleet = SimpleNamespace(local='laptop', estimates={
        'desktop': dict(age=14 * 3600 + 5, live=3), 'tower': dict(age=None, live=0)})
    line = fg.degraded_admission_line(
        fg.Admission(lock_host='laptop', owner='desktop', unreachable='desktop'), fleet)
    assert line == ("admission: desktop, tower unreachable; admitted locally against "
                    "desktop's last census (age 14h, 3 live), "
                    "no usable census of tower (counted 0 live)")
    # Owner lock skipped although its census answered: still never silent.
    line = fg.degraded_admission_line(
        fg.Admission(lock_host='laptop', owner='desktop', unreachable='desktop'),
        SimpleNamespace(local='laptop', estimates={}))
    assert line == 'admission: desktop unreachable; admitted locally against a fresh census of desktop'
    assert fg.degraded_admission_line(fg.Admission(lock_host='desktop', owner='desktop'),
                                      SimpleNamespace(local='laptop', estimates={})) == ''


def test_ssh_transport_cause_uses_only_final_line_and_fixed_safe_text(monkeypatch):
    peer = HostPeer('laptop', 'user@example.test', '/remote')
    for stderr, expected in (
        ('previous secret\nssh: connect to host peer port 22: No route to host\n', 'No route to host'),
        ('ssh: connect: Connection refused', 'Connection refused'),
        ('Permission denied (publickey).', 'Permission denied'),
        ('No route to host\nprivate unrecognized final line', None),
        ('', None),
        ('secret=private Connection timed out\x1b[31m', 'Connection timed out'),
    ):
        monkeypatch.setattr(fg.subprocess, 'run', lambda *a, **k:
                            SimpleNamespace(returncode=255, stdout='', stderr=stderr))
        state, error = fg.read_peer(peer)
        assert state is None and isinstance(error, fg.PeerUnreachable)
        assert 'secret' not in error and 'private' not in error and '\x1b' not in error
        if expected:
            assert expected in error
        else:
            assert str(error) == 'laptop governor unreachable (SSH transport failed)'


def cli_offline(tmp_path, monkeypatch, *, owner='desktop', host='desktop', cap=3,
                cached=None, policy=None):
    """A two-host deployment whose peer `laptop` is powered off."""
    from shantytown import config
    import time
    root = _roster(tmp_path, {'local': 'local-pane'})
    (root / 'shantytown.toml').write_text(
        f'[host]\nname="{host}"\n'
        + (f'admission_owner="{owner}"\n' if owner else '')
        + '[host.peers.laptop]\nssh="user@example.test"\nroot="/remote"\n')
    for name, retired in [('remote', False), ('retired', True)]:
        (root / 'crew' / (name + '.json')).write_text(json.dumps(
            dict(role='worker', host='laptop', harness='claude', retired=retired)))
    cfg = config.load(root)
    policy = policy or gov.Policy(tiers=(gov.Tier(at=50, min_priority=1),), max_agents=cap)
    local = gov.Governor(policy, FreshestReader({
        host: {'five_hour': Reading(pct=10, at=time.time())}}))
    monkeypatch.setattr(cli, '_local_governors', lambda a: (cfg, {'base': local}))
    monkeypatch.setattr(cli, 'Tmux', lambda *a, **k: _Panes({'local-pane': IDLE_SCREEN}))
    if cached is not None:
        peers = {'laptop': HostPeer('laptop', 'user@example.test', '/remote')}
        snap = sample('laptop', at=time.time() - 3 * 3600, cap=cap, agents=cached)
        snap['hosts'] = sorted([host, 'laptop'])
        snap['admission_owner'] = owner
        snap['governors']['base']['policy'] = fg.policy_wire(policy)
        fg.FleetGovernor(sample(host), [(snap, '')], root, peer_config=peers)
    def disconnected(*args, **kwargs):
        raise ConnectionRefusedError('asleep')
    monkeypatch.setattr(fg.subprocess, 'run', disconnected)
    monkeypatch.setattr(fg.subprocess, 'Popen', lambda *a, **k: (_ for _ in ()).throw(OSError('asleep')))
    monkeypatch.setattr(cli, '_window_launch_gate', lambda a: None)
    return _Args(root)


def test_cli_offline_peer_warnings_and_dispatch(tmp_path, monkeypatch, capsys):
    args = cli_offline(tmp_path, monkeypatch)
    args.governor = args.json = True
    assert cli._cmd_crew(args) == cli.OK
    output = json.loads(capsys.readouterr().out)
    assert output['errors'] == []
    # Never seen: its declared card is NOT charged; the peer is flagged instead.
    assert output['governors']['base']['live'] == 1
    assert 'never seen' in output['warnings'][0]
    card = next(c for c in cli._registry(args).all().exact() if c.name == 'local')
    assert cli._account_launch_refusal(args, card) == ''
    gate = cli._dispatch_gate(args)
    assert gate is None or not gate(None, 'local')
    args.json = False
    assert cli._cmd_crew(args) == cli.OK
    assert 'laptop unreachable' in capsys.readouterr().out


def _launch_degraded(args, card):
    cfg = cli.config.load(args.root)
    with cli._held_admission(args, cli._launch_admission_lock(args, card, cfg)):
        if hasattr(args, '_account_governor'):
            del args._account_governor
        return cli._launch_admitted(args, card, None, None, dry_run=True)


def test_owner_unreachable_admits_locally_under_cap_and_says_so(tmp_path, monkeypatch, capsys):
    args = cli_offline(tmp_path, monkeypatch, owner='laptop', host='desktop', cap=3,
                       cached=[agent('laptop', 'remote')])
    card = next(c for c in cli._registry(args).all().exact() if c.name == 'local')
    monkeypatch.setattr(cli, '_governor_agents', lambda a: [])
    monkeypatch.setattr(cli, '_account_launch_refusal', spy := _spy_refusal(monkeypatch))
    assert _launch_until_admitted(args, card) == 'admitted'
    err = capsys.readouterr().err
    assert spy.results == ['']
    assert err.count("admission: laptop unreachable; admitted locally against "
                     "laptop's last census (age 3h, 1 live)") == 1
    assert (args.root / 'governor' / 'admission.lock').is_file()


def _spy_refusal(monkeypatch):
    real = cli._account_launch_refusal
    def spy(a, card, **kw):
        result = real(a, card, **kw)
        spy.results.append(result)
        if not result:
            # Stop the dry run at the account gate: later launch steps are not under test.
            raise _Admitted()
        return result
    spy.results = []
    return spy


class _Admitted(Exception):
    pass


def _launch_until_admitted(args, card):
    try:
        return _launch_degraded(args, card)
    except _Admitted:
        return 'admitted'


def test_owner_unreachable_refuses_when_last_census_fills_the_cap(tmp_path, monkeypatch, capsys):
    args = cli_offline(tmp_path, monkeypatch, owner='laptop', cap=2,
                       cached=[agent('laptop', 'one'), agent('laptop', 'two')])
    card = next(c for c in cli._registry(args).all().exact() if c.name == 'local')
    monkeypatch.setattr(cli, '_governor_agents', lambda a: [])
    assert _launch_degraded(args, card) == cli.REFUSED
    err = capsys.readouterr().err
    assert '3/2' in err and 'admitted' not in err


def test_no_owner_with_peers_admits(tmp_path, monkeypatch, capsys):
    args = cli_offline(tmp_path, monkeypatch, owner=None, cap=3,
                       cached=[agent('laptop', 'remote')])
    card = next(c for c in cli._registry(args).all().exact() if c.name == 'local')
    monkeypatch.setattr(cli, '_governor_agents', lambda a: [])
    monkeypatch.setattr(cli, '_account_launch_refusal', spy := _spy_refusal(monkeypatch))
    assert _launch_until_admitted(args, card) == 'admitted'
    assert spy.results == ['']
    assert "against laptop's last census (age 3h, 1 live)" in capsys.readouterr().err


@pytest.mark.parametrize('policy_refusal', ['frozen', 'full-stop', 'gaming'])
def test_degraded_admission_keeps_real_policy_refusals(tmp_path, monkeypatch, capsys, policy_refusal):
    policy = None
    if policy_refusal == 'frozen':
        policy = gov.Policy(tiers=(gov.Tier(at=50, min_priority=1),),
                            on_signal_lost='freeze', max_agents=5)
    elif policy_refusal == 'full-stop':
        policy = gov.Policy(tiers=(gov.Tier(at=5, action='drain'),), max_agents=5)
    args = cli_offline(tmp_path, monkeypatch, owner='laptop', cap=5, policy=policy,
                       cached=[agent('laptop', 'remote')])
    if policy_refusal == 'frozen':
        import time
        stale = gov.Governor(policy, FreshestReader({'desktop': {'five_hour': Reading(
            pct=10, at=time.time() - 7200)}}))
        cfg = cli.config.load(args.root)
        monkeypatch.setattr(cli, '_local_governors', lambda a: (cfg, {'base': stale}))
    if policy_refusal == 'gaming':
        from shantytown import quiet_time
        held = SimpleNamespace(held=True, state='on', reasons=['gaming'],
                               refusal='gaming hold', render=lambda: 'gaming hold')
        monkeypatch.setattr(quiet_time, 'read', lambda root: held)
        monkeypatch.setattr(cli, '_refuse_gaming', lambda a, g: cli.REFUSED)
    card = next(c for c in cli._registry(args).all().exact() if c.name == 'local')
    monkeypatch.setattr(cli, '_governor_agents', lambda a: [])
    assert _launch_degraded(args, card) == cli.REFUSED
    err = capsys.readouterr().err
    assert 'admitted locally' not in err
    assert {'frozen': 'no account-governor override', 'full-stop': 'no account-governor override',
            'gaming': ''}[policy_refusal] in err


def test_tend_runs_fleet_sweeps_when_the_owner_is_unreachable():
    cfg = SimpleNamespace(host_name='laptop', host_admission_owner='desktop')
    assert not cli.runs_fleet_sweeps(cfg)
    assert cli.runs_fleet_sweeps(cfg, owner_unreachable=True)


def test_replacement_at_cap_reuses_only_its_local_slot(tmp_path, monkeypatch):
    args = fleet_setup(tmp_path, monkeypatch)
    card = cli._registry(args).all().exact()[0]
    assert '3/2' in cli._account_launch_refusal(args, card)
    assert cli._account_launch_refusal(args, card, replacing=True) == ''
    monkeypatch.setattr(cli, '_governor_agents', lambda a: [
        agent('laptop', 'local'), agent('laptop', 'extra')])
    assert '3/2' in cli._account_launch_refusal(args, card, replacing=True)


@pytest.mark.parametrize('mode', ['respawn', 'relaunch'])
def test_cycle_admission_refusal_never_stops_session(tmp_path, monkeypatch, mode):
    from shantytown import cycle
    from contextlib import contextmanager
    args = fleet_setup(tmp_path, monkeypatch)
    card = cli._registry(args).all().exact()[0]
    monkeypatch.setattr(cli, '_governor_agents', lambda a: [
        agent('laptop', 'local'), agent('laptop', 'extra')])
    monkeypatch.setattr(cli, '_window_launch_gate', lambda a: None)
    monkeypatch.setattr(cli, '_foreign_session_refusal', lambda *a: '')
    monkeypatch.setattr(cli, '_capture_history_before_kill', lambda *a: None)
    monkeypatch.setattr(cli, '_cmd_stop', lambda *a: pytest.fail('stopped live agent'))
    monkeypatch.setattr(cli, '_refresh_clone', lambda *a, **k: pytest.fail('mutated workspace'))
    held = []
    @contextmanager
    def lock(*a, **kw):
        assert not held, 'nested admission lock'
        held.append(True)
        try:
            yield
        finally:
            held.pop()
    monkeypatch.setattr(fg, 'admission_lock', lock)
    panes = SimpleNamespace(exists=lambda s: True)
    chosen = cycle.Plan(getattr(cycle, mode.upper()), 'fixture')
    rc, _ = cli._perform_cycle(args, card, card.name, 'fixture', panes, None,
                               chosen, SimpleNamespace(checkpoint='saved'))
    assert rc == cli.REFUSED
    assert not held and not hasattr(args, '_cycle_admission_locked')


def test_cycle_holds_admission_lock_from_preflight_through_relaunch(tmp_path, monkeypatch):
    from shantytown import cycle
    from contextlib import contextmanager
    args = fleet_setup(tmp_path, monkeypatch)
    card = cli._registry(args).all().exact()[0]
    monkeypatch.setattr(cli, '_window_launch_gate', lambda a: None)
    held, actions = [], []
    @contextmanager
    def lock(*a, **kw):
        assert not held
        held.append(True)
        try:
            yield
        finally:
            held.pop()
    monkeypatch.setattr(fg, 'admission_lock', lock)
    def stop(a):
        assert held
        actions.append('stop')
        monkeypatch.setattr(cli, '_governor_agents', lambda a: [])
        return cli.OK
    monkeypatch.setattr(cli, '_cmd_stop', stop)
    admitted = cli._launch_admitted
    def launch(a, card, panes, runtime, **kw):
        assert held
        if kw.get('dry_run'):
            actions.append('preflight')
            return admitted(a, card, panes, runtime, **kw)
        assert cli._account_launch_refusal(a, card) == ''
        actions.append('launch')
        return cli.OK
    monkeypatch.setattr(cli, '_launch_admitted', launch)
    panes = SimpleNamespace(exists=lambda s: True)
    runtime = SimpleNamespace(compose=lambda card: 'fixture launch')
    rc, mode = cli._perform_cycle(args, card, card.name, 'fixture', panes, runtime,
        cycle.Plan(cycle.RELAUNCH, 'fixture'), SimpleNamespace(checkpoint='saved'))
    assert rc == cli.OK and mode == cycle.RELAUNCH
    assert actions == ['preflight', 'stop', 'launch']
    assert not held


def test_governor_json_carries_what_the_status_bar_needs(tmp_path, monkeypatch, capsys):
    """aegis-apfuey: the shanty bar parsed the PROSE and went blind ("usage ?")
    when the prose changed shape. The bar pins the versioned JSON instead, so it
    must carry what the bar draws: per window pct / next tier / published, and
    the lane's effect (the tier sentence). Built from the SAME computation as the
    prose, so the two cannot disagree -- asserted here, not assumed."""
    from shantytown import config
    import time
    root = _roster(tmp_path, {'local': 'local-pane'})
    (root / 'shantytown.toml').write_text('[host]\nname="desktop"\n')
    cfg = config.load(root)
    policy = gov.Policy(tiers=(gov.Tier(at=50, min_priority=1),), max_agents=3)
    local = gov.Governor(policy, FreshestReader({
        'desktop': {'five_hour': Reading(pct=10, at=time.time())}}))
    monkeypatch.setattr(cli, '_local_governors', lambda a: (cfg, {'base': local}))
    monkeypatch.setattr(cli, 'Tmux', lambda *a, **k: _Panes({'local-pane': IDLE_SCREEN}))
    args = _Args(root)
    args.governor = args.json = True
    assert cli._cmd_crew(args) == cli.OK
    out = json.loads(capsys.readouterr().out)
    assert out['version'] == 1
    base = out['governors']['base']
    assert base['windows']['five_hour'] == dict(published=True, pct=10, next=50,
                                                reset_seconds=base['windows']['five_hour']['reset_seconds'])
    # CONTROL: an unpublished window is published=false with NULL numbers, never 0.
    assert base['windows']['seven_day'] == dict(published=False, pct=None, next=None,
                                                reset_seconds=None)
    assert base['effect'] == 'no restriction declared'
    args.json = False
    assert cli._cmd_crew(args) == cli.OK
    # The prose on this path is the single-lane form (`ok 10/50/- ?/?/? CAP[..]`).
    # Three prose shapes exist, which is exactly why the bar pins the JSON; here
    # only the numbers are cross-checked against it.
    first = capsys.readouterr().out.splitlines()[0].split()
    assert first[0] == 'ok' and first[1].split('/')[:2] == ['10', '50'] and first[2] == '?/?/?'
