"""Private unit fixtures only: no sudo, user creation or actual privilege change.

Native cross-UID acceptance remains a separate operator-admitted check.
"""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from shantytown import job_launch as jobs
from shantytown.actor_identity import IdentityError
from shantytown.ephemeral import Request


@pytest.fixture
def capability(tmp_path, monkeypatch):
    base = tmp_path / 'plans'
    base.mkdir(mode=0o700)
    (base / 'used').mkdir(mode=0o700)
    helper = tmp_path / 'fixed-helper'
    helper.write_text('fixture, never executed')
    helper.chmod(0o700)
    monkeypatch.setattr(jobs, 'BASE', base)
    monkeypatch.setattr(jobs, 'HELPER', helper)
    monkeypatch.setattr(jobs, 'OWNER', os.geteuid())
    # Substitute only the trust anchor for this unprivileged unit fixture.
    # load's no-follow FD, file owner/mode/size/schema checks still run.
    def fixture_protected(path, **kwargs):
        path = Path(path)
        assert path.is_relative_to(tmp_path)
        if path.is_symlink() or path.lstat().st_mode & 0o022:
            raise IdentityError('untrusted fixture')
    monkeypatch.setattr(jobs, 'protected', fixture_protected)
    principal = 'eph-task-123abc'
    home = '/var/lib/shantytown/agents/crew-' + principal
    spec = dict(version=1, principal=principal, controller_uid=os.geteuid(),
                uid=51001, gid=51001, username='_stjobs', home=home,
                root=str(tmp_path / 'root'), workspace=home + '/worktree',
                settings=home + '/codex/config.toml', harness='codex',
                request=jobs.request_fields(Request('task', 'item-1', harness='codex')),
                argv=['/usr/bin/true'], environment={'PATH': '/usr/bin:/bin', 'CODEX_HOME': home + '/codex'})
    path = base / (principal + '.json')
    def save(value=spec):
        path.write_text(json.dumps(value))
        path.chmod(0o600)
    save()
    return spec, save, path


def test_exact_registered_capability_and_no_controller_environment_forwarded(capability, monkeypatch):
    spec, _, _ = capability
    _, digest = jobs.load(spec['principal'])
    monkeypatch.setenv('QUIPU_AUTH_TOKEN', 'synthetic-not-issued')
    monkeypatch.setenv('SSH_AUTH_SOCK', '/synthetic-controller-socket')
    seen = []
    def run(argv, **kwargs):
        seen.append(argv)
        assert argv == ['/usr/bin/sudo', '-n', '--', str(jobs.HELPER), 'check', spec['principal'], digest]
        assert kwargs['env'] == {'PATH': '/usr/bin:/bin'}
        assert kwargs['timeout'] == 10
        return SimpleNamespace(returncode=0, stdout='READY ' + digest)
    monkeypatch.setattr(jobs.subprocess, 'run', run)
    assert jobs.select(Request('task', 'item-1', harness='codex'), root=spec['root'],
                       harness='codex', used=set()) == (spec, digest)
    assert len(seen) == 1
    assert 'launch' in jobs.command(spec, digest)
    assert jobs.command(spec, digest).endswith(spec['principal'] + ' ' + digest)


@pytest.mark.parametrize('change', [
    {'uid': 501}, {'gid': 0}, {'gid': 51002}, {'controller_uid': 51001}, {'username': 'root'},
    {'home': '/home/controller'}, {'workspace': '/home/controller/worktree'},
    {'settings': '/home/controller/config.toml'}, {'environment': {'SSH_AUTH_SOCK': 'fixture'}},
    {'environment': {'CODEX_HOME': '/home/controller/.codex'}}, {'argv': ['relative-command']},
    {'principal': 'boss'}, {'harness': 'unknown'}, {'request': {'job': 'task'}},
])
def test_unbound_shared_or_partial_capability_refuses(capability, change):
    spec, save, _ = capability
    save(dict(spec, **change))
    with pytest.raises(IdentityError):
        jobs.load(spec['principal'])


@pytest.mark.parametrize('fault', ['used', 'wrong-request', 'wrong-controller', 'duplicate-uid',
                                   'failed-switch', 'missing-helper'])
def test_no_fallback_or_privileged_attempt_for_bad_selection(capability, monkeypatch, fault):
    spec, save, _ = capability
    seen = []
    def run(*args, **kwargs):
        seen.append(args)
        return SimpleNamespace(returncode=1, stdout='')
    monkeypatch.setattr(jobs.subprocess, 'run', run)
    used = set()
    if fault == 'used':
        used.add(spec['principal'])
    elif fault == 'wrong-request':
        save(dict(spec, request=jobs.request_fields(Request('task', 'other'))))
    elif fault == 'wrong-controller':
        save(dict(spec, controller_uid=spec['controller_uid'] + 1))
    elif fault == 'duplicate-uid':
        other = dict(spec, principal='eph-task-000001')
        (jobs.BASE / 'eph-task-000001.json').write_text(json.dumps(other))
    elif fault == 'missing-helper':
        jobs.HELPER.unlink()
    with pytest.raises((IdentityError, OSError)):
        jobs.select(Request('task', 'item-1', harness='codex'), root=spec['root'], harness='codex', used=used)
    assert len(seen) == (1 if fault == 'failed-switch' else 0)


def test_symlink_or_writable_manifest_is_not_a_capability(capability):
    spec, _, path = capability
    path.chmod(0o666)
    with pytest.raises(IdentityError):
        jobs.load(spec['principal'])
    path.chmod(0o600)
    target = path.with_suffix('.saved')
    path.rename(target)
    path.symlink_to(target)
    with pytest.raises(IdentityError):
        jobs.load(spec['principal'])


def test_same_uid_is_never_recycled_even_after_failed_launch(capability):
    spec, _, _ = capability
    digest = jobs.load(spec['principal'])[1]
    jobs.consume(spec, digest)
    assert json.loads((jobs.BASE / 'used' / (spec['principal'] + '.json')).read_text())['uid'] == spec['uid']
    other = dict(spec, principal='eph-task-000001')
    with pytest.raises(IdentityError, match='already used'):
        jobs.consume(other, digest)


@pytest.mark.parametrize('fault', ['missing', 'wrong-hash', 'wrong-uid', 'wrong-root', 'wrong-workspace', 'wrong-harness'])
def test_runtime_cannot_replace_its_admitted_binding(capability, monkeypatch, fault):
    spec, _, _ = capability
    from shantytown import ephemeral
    digest = jobs.load(spec['principal'])[1]
    binding = {'sha256': digest, 'uid': spec['uid']}
    if fault == 'missing': binding = None
    elif fault == 'wrong-hash': binding['sha256'] = '0' * 64
    elif fault == 'wrong-uid': binding['uid'] += 1
    card = SimpleNamespace(name=spec['principal'], dangerous=True, workspace=spec['workspace'], harness=spec['harness'])
    root = spec['root']
    if fault == 'wrong-root': root += '-wrong'
    elif fault == 'wrong-workspace': card.workspace += '-wrong'
    elif fault == 'wrong-harness': card.harness = 'claude'
    monkeypatch.setattr(ephemeral, 'read', lambda *a: {'uid_binding': binding})
    with pytest.raises(IdentityError): jobs.for_card(root, card)


def test_same_uid_spoofed_sudo_environment_never_reaches_loader(monkeypatch):
    monkeypatch.setenv('SUDO_UID', '0')
    monkeypatch.setenv('SHANTY_AGENT', 'boss')
    monkeypatch.setattr(jobs.os, 'geteuid', lambda: 51001)
    monkeypatch.setattr(jobs, 'load', lambda *a: pytest.fail('unprivileged caller reached protected loader'))
    assert jobs.main(['launch', 'eph-task-123abc', '0' * 64]) == 1


@pytest.mark.parametrize('platform', ['darwin', 'linux'])
@pytest.mark.parametrize('fails', [False, True])
def test_irreversible_drop_order_and_failure_never_execs(monkeypatch, platform, fails):
    import ctypes
    import resource
    monkeypatch.setattr(jobs.sys, 'platform', platform)
    events = []
    current = dict(uid=0, gid=0, groups=[0])
    monkeypatch.setattr(jobs.os, 'setgroups', lambda value: (events.append('groups'), current.update(groups=value)))
    monkeypatch.setattr(jobs.os, 'setgid', lambda value: (events.append('gid'), current.update(gid=value)))
    def setuid(value):
        events.append('uid')
        if fails: raise PermissionError('synthetic failed switch')
        current['uid'] = value
    monkeypatch.setattr(jobs.os, 'setuid', setuid)
    monkeypatch.setattr(jobs.os, 'getuid', lambda: current['uid'])
    monkeypatch.setattr(jobs.os, 'geteuid', lambda: current['uid'])
    monkeypatch.setattr(jobs.os, 'getgid', lambda: current['gid'])
    monkeypatch.setattr(jobs.os, 'getegid', lambda: current['gid'])
    monkeypatch.setattr(jobs.os, 'getgroups', lambda: current['groups'])
    monkeypatch.setattr(ctypes, 'CDLL', lambda *a, **k: SimpleNamespace(prctl=lambda *args: 0))
    monkeypatch.setattr(resource, 'getrlimit', lambda _: (1024, 1024))
    monkeypatch.setattr(jobs.os, 'chdir', lambda path: events.append('cwd'))
    monkeypatch.setattr(jobs.os, 'closerange', lambda *args: events.append('fds'))
    monkeypatch.setenv('PRIVATE_CONTROLLER_CREDENTIAL', 'synthetic-not-issued')
    def execute(path, argv, environment):
        assert current == {'uid': 51001, 'gid': 51001, 'groups': []}
        assert 'PRIVATE_CONTROLLER_CREDENTIAL' not in environment
        assert environment['HOME'] == '/private/job'
        events.append('exec')
    monkeypatch.setattr(jobs.os, 'execve', execute)
    spec = dict(uid=51001, gid=51001, home='/private/job', username='_stjobs',
                principal='eph-task-123abc', root='/private/control', workspace='/private/job/work',
                argv=['/usr/bin/true'], environment={})
    if fails:
        with pytest.raises(PermissionError): jobs.execute(spec)
        assert events == ['groups', 'gid', 'uid']
    else:
        jobs.execute(spec)
        assert events == ['groups', 'gid', 'uid', 'cwd', 'fds', 'exec']


def test_preview_never_executes_a_privileged_probe(capability, monkeypatch):
    spec, _, _ = capability
    monkeypatch.setattr(jobs.subprocess, 'run', lambda *a, **k: pytest.fail('preview executed a helper'))
    selected, digest = jobs.select(Request('task', 'item-1', harness='codex'), root=spec['root'],
                                   harness='codex', used=set(), native_probe=False)
    assert selected == spec and len(digest) == 64
