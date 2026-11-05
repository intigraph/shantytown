import json
import os
from types import SimpleNamespace
import pytest
from shantytown import actor_identity as identity

@pytest.fixture
def policy(tmp_path, monkeypatch):
    monkeypatch.setattr(identity, 'TRUSTED_POLICY_OWNER', os.geteuid())
    for name in ('SHANTY_AGENT','SEEDS_ACTOR','QUIPU_AGENT'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(identity.os, 'geteuid', lambda: 51001)
    p=tmp_path/'identity.json'
    p.write_text(json.dumps({'version':1,'required':True,'users':{str(os.geteuid()):{
        'principal':'synthetic-owner','home':str(tmp_path),'endpoint':'https://example.test','sd':'/usr/bin/sd'}}}))
    p.chmod(0o644)
    return p

def answer(principal='synthetic-owner', **changes):
    data=dict(authenticated=True, auth_class='attested_session',principal=principal,key_id='sha256:'+'a'*64,session='synthetic-session')
    data.update(changes)
    return SimpleNamespace(returncode=0,stdout=json.dumps(data))

def test_key_identity_uses_pinned_endpoint_home_and_no_actor_override(policy, monkeypatch):
    monkeypatch.setenv('SEEDS_QUIPU_URL','https://untrusted.test')
    def run(argv, **kwargs):
        assert argv==['/usr/bin/sd','--quipu','https://example.test','identity','--json']
        assert kwargs['env']['HOME']==str(policy.parent)
        assert 'SEEDS_QUIPU_URL' not in kwargs['env']
        return answer()
    assert identity.authenticated_actor(policy_path=policy,run=run)=='synthetic-owner'

@pytest.mark.parametrize('field',['SHANTY_AGENT','SEEDS_ACTOR','QUIPU_AGENT'])
def test_spoofed_env_refused(policy,monkeypatch,field):
    monkeypatch.setenv(field,'synthetic-other')
    with pytest.raises(identity.IdentityError,match='differs'):
        identity.authenticated_actor(policy_path=policy,run=lambda *a,**k:answer())

@pytest.mark.parametrize('result',[answer('synthetic-other'),answer(authenticated=False),answer(auth_class='named_bearer'),answer(key_id=None),answer(session='')])
def test_unkeyed_or_wrong_binding_refused(policy,result):
    with pytest.raises(identity.IdentityError):
        identity.authenticated_actor(policy_path=policy,run=lambda *a,**k:result)

def test_policy_permissions_and_symlink_refused(policy):
    policy.chmod(0o666)
    with pytest.raises(identity.IdentityError):identity.authenticated_actor(policy_path=policy)
    policy.chmod(0o644)
    link=policy.with_name('link');link.symlink_to(policy)
    with pytest.raises(identity.IdentityError):identity.authenticated_actor(policy_path=link)

def test_foreign_uid_cannot_select_another_agents_binding(policy,monkeypatch):
    monkeypatch.setattr(identity.os,'geteuid',lambda:123456)
    with pytest.raises(identity.IdentityError,match='Unix UID'):
        identity.authenticated_actor(policy_path=policy)

def test_no_policy_is_explicit_unmigrated_mode(tmp_path):
    assert identity.authenticated_actor(policy_path=tmp_path/'absent') is None

def test_launcher_drops_privilege_and_never_forwards_controller_credentials(monkeypatch):
    from shantytown import isolated_launch
    monkeypatch.setattr(isolated_launch.os,'geteuid',lambda:0)
    argv=isolated_launch.isolated_invocation(['/bin/true'],uid=51001,gid=51001,
        home='/var/lib/shantytown/agents/crew-synthetic',principal='synthetic',
        env={'PATH':'/usr/bin:/bin','QUIPU_AUTH_TOKEN':'synthetic-not-issued','SSH_AUTH_SOCK':'fixture','UNEXPECTED_SECRET':'fixture'})
    assert '--clear-groups'in argv and '--no-new-privs'in argv and '--bounding-set=-all'in argv
    assert not any('TOKEN'in x or 'SECRET'in x or 'SSH_AUTH'in x for x in argv)
    assert 'SHANTY_AGENT=synthetic'in argv
    monkeypatch.setattr(isolated_launch.os,'geteuid',lambda:1000)
    with pytest.raises(identity.IdentityError,match='separate privileged controller'):
        isolated_launch.isolated_invocation(['/bin/true'],uid=51001,gid=51001,
            home='/var/lib/shantytown/agents/crew-synthetic',principal='synthetic')

def test_protected_launch_mapping_cannot_be_selected_by_other_uid(policy,monkeypatch):
    from shantytown import isolated_launch
    monkeypatch.setattr(identity,'POLICY_PATH',policy)
    monkeypatch.setattr(identity.os, 'geteuid', lambda: 51002)
    # Another Unix identity cannot select the owner's launch binding.
    with pytest.raises(identity.IdentityError):
        isolated_launch.wrap(SimpleNamespace(name='synthetic-owner'),'echo fixture')

def test_inbox_sender_cannot_override_verified_principal(monkeypatch):
    from shantytown import cli
    monkeypatch.setattr(identity, 'authenticated_actor', lambda: 'synthetic-owner')
    monkeypatch.delenv('TMUX_PANE', raising=False)
    assert cli._verified_sender(SimpleNamespace(me=None), None) == ('synthetic-owner', True)
    assert cli._verified_sender(SimpleNamespace(me='synthetic-other'), None) == (None, False)

def test_unkeyed_command_refuses_before_dispatch(monkeypatch, tmp_path):
    from shantytown import cli
    called = []
    def refuse():
        raise identity.IdentityError('synthetic unkeyed request')
    monkeypatch.setattr(identity, 'authenticated_actor', refuse)
    monkeypatch.setattr(cli, '_run_command', lambda a: called.append(a) or 0)
    assert cli.main(['--registry', 'files', '--root', str(tmp_path), 'anchor']) == cli.REFUSED
    assert called == []

def test_key_policy_refuses_unsigned_peer_transport_before_ssh(policy, monkeypatch):
    from shantytown import cli
    monkeypatch.setattr(identity, 'POLICY_PATH', policy)
    monkeypatch.setattr(cli.subprocess if hasattr(cli, 'subprocess') else __import__('subprocess'), 'run',
                        lambda *a, **k: pytest.fail('unsigned relay must not start SSH'))
    with pytest.raises(identity.IdentityError, match='key-authenticated broker'):
        cli._peer_inbox_ssh(SimpleNamespace(), 'synthetic-other', 'fixture', 'synthetic-owner')

@pytest.fixture
def pinned_config(policy, monkeypatch):
    import hashlib
    from shantytown import job_launch
    directory = policy.parent / 'operator-config'
    (directory / 'seeds').mkdir(parents=True)
    directory.chmod(0o755)
    (directory / 'seeds').chmod(0o755)
    ca = directory / 'roots.pem'
    ca.write_bytes(b'synthetic public CA bytes')
    config = directory / 'seeds' / 'config.toml'
    config.write_text('[quipu]\nca_file = ' + json.dumps(str(ca)) + '\nca_sha256 = "' +
                      hashlib.sha256(ca.read_bytes()).hexdigest() + '"\n')
    ca.chmod(0o644)
    config.chmod(0o644)
    data = json.loads(policy.read_text())
    data['users']['51001']['seeds_config_dir'] = str(directory)
    policy.write_text(json.dumps(data))
    # Exercise real files/digests but keep the temporary fixture's writable
    # ancestors separate from the production immutable-chain verifier.
    def protected(path, *, directory=False):
        path = __import__('pathlib').Path(path)
        if path.is_symlink() or path.stat().st_mode & 0o022:
            raise identity.IdentityError('mutable or linked protected input')
        assert path.is_dir() if directory else path.is_file()
    monkeypatch.setattr(job_launch, 'protected', protected)
    monkeypatch.setattr(identity, 'POLICY_PATH', policy)
    return directory, ca, config


def test_identity_forwards_only_protected_seeds_config(policy, pinned_config, monkeypatch):
    directory, _, _ = pinned_config
    monkeypatch.setenv('XDG_CONFIG_HOME', '/untrusted/controller-config')
    def run(argv, **kwargs):
        assert kwargs['env']['XDG_CONFIG_HOME'] == str(directory)
        assert kwargs['env']['HOME'] == str(policy.parent)
        return answer()
    assert identity.authenticated_actor(policy_path=policy, run=run) == 'synthetic-owner'


@pytest.mark.parametrize('fault', ['changed-ca', 'missing-ca', 'bad-config', 'relative-ca',
                                    'missing-pin', 'writable-ca', 'linked-ca', 'writable-config'])
def test_protected_ca_failures_refuse_before_sd(policy, pinned_config, fault):
    directory, ca, config = pinned_config
    if fault == 'changed-ca': ca.write_bytes(b'changed bytes')
    elif fault == 'missing-ca': ca.unlink()
    elif fault == 'bad-config': config.write_text('invalid = [')
    elif fault == 'relative-ca': config.write_text('[quipu]\nca_file="relative.pem"\nca_sha256="'+'a'*64+'"\n')
    elif fault == 'missing-pin': config.write_text('[quipu]\nca_file='+json.dumps(str(ca))+'\n')
    elif fault == 'writable-ca': ca.chmod(0o666)
    elif fault == 'linked-ca':
        ca.rename(directory / 'other.pem')
        ca.symlink_to(directory / 'other.pem')
    elif fault == 'writable-config': config.chmod(0o666)
    with pytest.raises(identity.IdentityError):
        identity.authenticated_actor(policy_path=policy, run=lambda *a, **k: pytest.fail('sd must not run'))


def test_job_exec_carries_protected_config_after_drop(policy, pinned_config, monkeypatch):
    from shantytown import job_launch
    import resource
    directory, _, _ = pinned_config
    monkeypatch.setattr(resource, 'getrlimit', lambda _: (1024, 1024))
    events = []
    monkeypatch.setattr(job_launch, 'drop_identity', lambda spec: events.append('drop'))
    monkeypatch.setattr(job_launch.os, 'chdir', lambda path: None)
    monkeypatch.setattr(job_launch.os, 'closerange', lambda *args: None)
    def execute(path, argv, environment):
        assert events == ['drop']
        assert environment['XDG_CONFIG_HOME'] == str(directory)
        assert 'QUIPU_AUTH_TOKEN' not in environment
        events.append('exec')
    monkeypatch.setattr(job_launch.os, 'execve', execute)
    job_launch.execute(dict(home=str(policy.parent), username='_stjobs', principal='synthetic-owner',
                           root='/private/job', workspace=str(policy.parent),
                           environment={}, argv=['/usr/bin/true']))
    assert events == ['drop', 'exec']


def test_job_attestation_uses_protected_config_after_drop(policy, pinned_config, monkeypatch):
    from shantytown import job_launch
    directory, _, _ = pinned_config
    monkeypatch.setattr(job_launch, 'drop_identity', lambda spec: None)
    monkeypatch.setattr(job_launch.os, 'environ', {'XDG_CONFIG_HOME': '/untrusted'})
    monkeypatch.setattr(job_launch.os, 'chdir', lambda path: None)
    def authenticated():
        assert job_launch.os.environ['XDG_CONFIG_HOME'] == str(directory)
        return 'synthetic-owner'
    monkeypatch.setattr(identity, 'authenticated_actor', authenticated)
    job_launch.attest_job(dict(home=str(policy.parent), principal='synthetic-owner'))


# Exercise the real adapter transport with a fully mocked subprocess runner.
@pytest.mark.real_store
@pytest.mark.parametrize('args', [('show', 'sd-fixture'), ('update', 'sd-fixture', '--title', 'fixture')])
def test_tracker_pins_config_for_reads_and_writes_without_advise_override(policy, pinned_config, monkeypatch, args):
    from shantytown import sd, advise_signing
    directory, _, _ = pinned_config
    tracker = sd.SdTracker(quipu='https://example.test', prefix='sd')
    monkeypatch.setattr(tracker, 'prove_store', lambda: None)
    monkeypatch.setattr(identity, 'authenticated_actor', lambda: 'synthetic-owner')
    monkeypatch.setattr(advise_signing, 'run', lambda *a, **k: pytest.fail('observe profile cannot override protected config'))
    monkeypatch.setenv('XDG_CONFIG_HOME', '/untrusted')
    def run(argv, **kwargs):
        assert kwargs['env']['XDG_CONFIG_HOME'] == str(directory)
        return SimpleNamespace(returncode=0, stdout='{}')
    monkeypatch.setattr(sd.subprocess, 'run', run)
    assert tracker._bd_in(str(policy.parent), *args).returncode == 0


def test_same_uid_harness_launch_retains_protected_config(policy, pinned_config):
    import shlex
    from shantytown import isolated_launch
    directory, _, _ = pinned_config
    argv = shlex.split(isolated_launch.wrap(SimpleNamespace(name='synthetic-owner'), 'echo fixture'))
    assert 'XDG_CONFIG_HOME=' + str(directory) in argv
    assert 'HOME=' + str(policy.parent) in argv


@pytest.mark.real_store
def test_store_proof_uses_the_same_protected_config(policy, pinned_config, monkeypatch):
    from shantytown import sd
    directory, _, _ = pinned_config
    tracker = sd.SdTracker(quipu='https://example.test', prefix='sd')
    def run(argv, **kwargs):
        assert kwargs['env']['XDG_CONFIG_HOME'] == str(directory)
        assert argv[-2:] == ['where', '--json']
        return SimpleNamespace(returncode=0, stdout=json.dumps(dict(
            location_source='--quipu', quipu_url='https://example.test', prefix='sd', graph='urn:fixture')))
    monkeypatch.setattr(sd.subprocess, 'run', run)
    assert tracker.prove_store().graph == 'urn:fixture'
