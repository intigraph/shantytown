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
