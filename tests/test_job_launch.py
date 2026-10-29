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
def metadata(capability, tmp_path, monkeypatch):
    from shantytown import job_metadata
    spec, _, _ = capability
    digest = jobs.load(spec['principal'])[1]
    spec = dict(spec, root=str(tmp_path / 'stores' / spec['principal']))
    monkeypatch.setattr(job_metadata, 'BASE', tmp_path / 'stores')
    monkeypatch.setattr(jobs, 'load', lambda _: (spec, digest))
    monkeypatch.setattr(jobs, 'inventory', lambda: [(spec, digest)])
    monkeypatch.setattr(jobs.os, 'geteuid', lambda: 0)
    return job_metadata, spec, digest


def test_metadata_contains_only_own_card_and_disabled_policy(metadata):
    from shantytown import config
    from shantytown.files import FilesRegistry
    module, spec, digest = metadata
    assert module.prepare(spec['principal'], digest) == 'CREATED'
    root = Path(spec['root'])
    cards = FilesRegistry(root / 'crew').all().exact()
    assert [card.name for card in cards] == [spec['principal']]
    assert cards[0].reports_to is None and cards[0].pane is None
    policy = config.load(root).ephemeral
    assert policy.require_verified_identity and not policy.unattended_uid_ready
    assert policy.unattended is False and policy.max_agents == 0
    rendered = b''.join(module.contents(spec).values())
    assert spec['controller_root'].encode() not in rendered
    assert b'key' not in rendered and b'endpoint' not in rendered
    assert module.prepare(spec['principal'], digest) == 'UNCHANGED'


@pytest.mark.parametrize('fault', ['extra', 'changed', 'symlink'])
def test_metadata_does_not_adopt_foreign_or_modified_store(metadata, fault):
    module, spec, digest = metadata
    module.prepare(spec['principal'], digest)
    root = Path(spec['root'])
    path = root / 'shantytown.toml'
    if fault == 'extra':
        (root / 'controller-credential.json').write_text('synthetic-not-a-key')
    elif fault == 'changed':
        path.write_text('[ephemeral]\nunattended_uid_ready=true\n')
    else:
        path.unlink()
        path.symlink_to(root / 'absent')
    with pytest.raises(IdentityError):
        module.prepare(spec['principal'], digest)


def test_metadata_preserves_interrupted_staging_and_rejects_changed_digest(metadata):
    module, spec, digest = metadata
    module.BASE.mkdir(mode=0o755)
    staging = module.BASE / ('.' + spec['principal'] + '.pending')
    staging.mkdir(mode=0o700)
    marker = staging / 'interrupted'
    marker.write_text('retain')
    with pytest.raises(IdentityError):
        module.prepare(spec['principal'], 'b' * 64)
    with pytest.raises(FileExistsError):
        module.prepare(spec['principal'], digest)
    assert marker.read_text() == 'retain' and not Path(spec['root']).exists()


def test_metadata_nonroot_refuses_before_manifest_read(metadata, monkeypatch):
    module, spec, digest = metadata
    monkeypatch.setattr(jobs.os, 'geteuid', lambda: 501)
    monkeypatch.setattr(jobs, 'load', lambda *a: (_ for _ in ()).throw(AssertionError('manifest read')))
    with pytest.raises(IdentityError, match='root execution'):
        module.prepare(spec['principal'], digest)


@pytest.mark.parametrize('caller', ['controller', 'job', 'foreign'])
def test_metadata_fixed_helper_operation_requires_its_controller(metadata, monkeypatch, caller):
    module, spec, digest = metadata
    original = jobs.protected
    monkeypatch.setattr(jobs, 'protected', lambda path, **kw:
                        None if Path(path) == Path(jobs.__file__).absolute() else original(path, **kw))
    uid = {'controller': spec['controller_uid'], 'job': spec['uid'], 'foreign': spec['uid'] + 1}[caller]
    monkeypatch.setenv('SUDO_UID', str(uid))
    monkeypatch.setattr(jobs, 'check_native', lambda *a, **kw:
                        (_ for _ in ()).throw(AssertionError('launch attempted')))
    assert jobs.main(['prepare', spec['principal'], digest]) == (0 if caller == 'controller' else 1)
    assert Path(spec['root']).exists() == (caller == 'controller')


def test_launch_rechecks_own_key_before_consuming_or_executing(capability, monkeypatch):
    spec, _, _ = capability
    digest = jobs.load(spec['principal'])[1]
    original = jobs.protected
    monkeypatch.setattr(jobs, 'protected', lambda path, **kw:
                        None if Path(path) == Path(jobs.__file__).absolute() else original(path, **kw))
    monkeypatch.setattr(jobs.os, 'geteuid', lambda: 0)
    monkeypatch.setenv('SUDO_UID', str(spec['controller_uid']))
    calls = []
    monkeypatch.setattr(jobs, 'check_native', lambda *a, **kw: calls.append('native'))
    def failed_key(*a):
        calls.append('own-key')
        raise IdentityError('attestation changed after admission')
    monkeypatch.setattr(jobs, 'probe', failed_key)
    monkeypatch.setattr(jobs, 'consume', lambda *a:
                        (_ for _ in ()).throw(AssertionError('UID consumed')))
    monkeypatch.setattr(jobs, 'execute', lambda *a:
                        (_ for _ in ()).throw(AssertionError('harness executed')))
    assert jobs.main(['launch', spec['principal'], digest]) == 1
    assert calls == ['native', 'own-key']
    assert list((jobs.BASE / 'used').iterdir()) == []


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
    monkeypatch.setattr(jobs.os, 'geteuid', lambda: 51000)
    spec = dict(version=1, principal=principal, controller_uid=51000,
                uid=51001, gid=51001, username='_stjobs', home=home,
                root='/var/lib/shantytown/job-stores/' + principal,
                controller_root=str(tmp_path / 'root'), workspace=home + '/worktree',
                settings=home + '/codex/config.toml', harness='codex', review=None,
                request=jobs.request_fields(Request('task', 'item-1', harness='codex')),
                argv=['/usr/bin/true'], environment={'PATH': '/usr/bin:/bin', 'CODEX_HOME': home + '/codex'})
    path = base / (principal + '.json')
    def save(value=spec):
        path.write_text(json.dumps(value))
        path.chmod(0o600)
    save()
    import hashlib
    plan = {'version': 1, 'uid_min': 51001, 'uid_max': 51016,
            'slots': {principal: {'uid': spec['uid'], 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}}}
    (base / 'slots.json').write_text(json.dumps(plan))
    (base / 'slots.json').chmod(0o600)
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
        assert kwargs['timeout'] == 30
        return SimpleNamespace(returncode=0, stdout='READY ' + digest)
    monkeypatch.setattr(jobs.subprocess, 'run', run)
    assert jobs.select(Request('task', 'item-1', harness='codex'), root=spec['controller_root'],
                       harness='codex', used=set()) == (spec, digest)
    assert len(seen) == 1
    assert 'launch' in jobs.command(spec, digest)
    assert jobs.command(spec, digest).endswith(spec['principal'] + ' ' + digest)


@pytest.mark.parametrize('change', [
    {'uid': 501}, {'gid': 0}, {'gid': 51002}, {'controller_uid': 501}, {'controller_uid': 9999}, {'controller_uid': 51001}, {'username': 'root'},
    {'home': '/synthetic-controller'}, {'workspace': '/synthetic-controller/worktree'},
    {'settings': '/synthetic-controller/config.toml'},
    {'root': '/synthetic-controller'}, {'controller_root': '/var/lib/shantytown'}, {'environment': {'SSH_AUTH_SOCK': 'fixture'}},
    {'environment': {'CODEX_HOME': '/synthetic-controller/.codex'}}, {'argv': ['relative-command']},
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
        jobs.select(Request('task', 'item-1', harness='codex'), root=spec['controller_root'], harness='codex', used=used)
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


@pytest.mark.parametrize('fault', ['none', 'duplicate-uid', 'job-controller'])
def test_direct_helper_checks_inventory_before_native_probe(capability, monkeypatch, fault):
    spec, _, _ = capability
    digest = jobs.load(spec['principal'])[1]
    if fault != 'none':
        other = dict(spec, principal='eph-task-000001', uid=51002, gid=51002)
        if fault == 'duplicate-uid':
            other.update(uid=spec['uid'], gid=spec['gid'])
        else:
            other['controller_uid'] = spec['uid']
            other['username'] = '_stjobs_000001'
        path = jobs.BASE / 'eph-task-000001.json'
        path.write_text(json.dumps(other))
        path.chmod(0o600)
        import hashlib
        plan_path = jobs.BASE / 'slots.json'
        plan = json.loads(plan_path.read_text())
        plan['slots'][other['principal']] = {'uid': other['uid'], 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        plan_path.write_text(json.dumps(plan))
    # Simulate only the separately admitted root entrypoint, never elevate the
    # test process. Keep real manifest decoding/inventory validation intact.
    monkeypatch.setattr(jobs.os, 'geteuid', lambda: 0)
    monkeypatch.setenv('SUDO_UID', str(spec['controller_uid']))
    protected = jobs.protected
    monkeypatch.setattr(jobs, 'protected', lambda path, **kw:
                        None if Path(path) == Path(jobs.__file__).absolute()
                        else protected(path, **kw))
    calls = []
    monkeypatch.setattr(jobs, 'check_native', lambda value: calls.append('native'))
    monkeypatch.setattr(jobs, 'probe', lambda value: calls.append('probe'))
    assert jobs.main(['check', spec['principal'], digest]) == (0 if fault == 'none' else 1)
    assert calls == (['native', 'probe'] if fault == 'none' else [])


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
    root = spec['controller_root']
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
        assert environment['SHANTY_ROOT'] == '/private/job-store'
        assert '/private/control' not in environment.values()
        events.append('exec')
    monkeypatch.setattr(jobs.os, 'execve', execute)
    spec = dict(uid=51001, gid=51001, home='/private/job', username='_stjobs',
                principal='eph-task-123abc', root='/private/job-store', controller_root='/private/control',
                workspace='/private/job/work',
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
    selected, digest = jobs.select(Request('task', 'item-1', harness='codex'), root=spec['controller_root'],
                                   harness='codex', used=set(), native_probe=False)
    assert selected == spec and len(digest) == 64


@pytest.mark.parametrize('fault', ['none', 'permission', 'persistent', 'unknown'])
def test_uid_stop_drops_before_signalling_and_refuses_unknown(capability, monkeypatch, fault):
    spec, _, _ = capability
    actions = []
    monkeypatch.setattr(jobs, 'drop_identity', lambda _: actions.append('drop'))
    snapshots = iter([[912], []])
    def snapshot(uid):
        assert actions[0] == 'drop' and uid == spec['uid']
        if fault == 'unknown':
            raise IdentityError('unreadable ps')
        return [912] if fault == 'persistent' else next(snapshots)
    def kill(pid, sig):
        assert actions[0] == 'drop'
        actions.append(('kill', pid))
        if fault == 'permission':
            raise PermissionError('recycled into another UID')
    monkeypatch.setattr(jobs, 'running_uid', snapshot)
    monkeypatch.setattr(jobs.os, 'kill', kill)
    import time
    monkeypatch.setattr(time, 'sleep', lambda _: None)
    if fault == 'none':
        jobs.stop_uid(spec)
        assert actions == ['drop', ('kill', 912)]
    else:
        with pytest.raises((IdentityError, PermissionError)):
            jobs.stop_uid(spec)
        assert actions[0] == 'drop'
        if fault == 'unknown':
            assert actions == ['drop']


@pytest.mark.parametrize('output,code,expected', [
    ('51001 912 S\n501 913 S\n51001 914 Z\n', 0, [912]),
    ('', 0, None), ('51001 nonsense S\n', 0, None),
    ('51001 912 S\n', 1, None), ('51001 1 S\n', 0, None),
])
def test_native_uid_snapshot_never_treats_unknown_as_empty(monkeypatch, output, code, expected):
    class Process:
        pid = 999
        returncode = code
        def communicate(self, timeout=None):
            return output, ''
    def popen(argv, **kwargs):
        assert argv == ['/bin/ps', '-axo', 'uid=,pid=,stat=']
        assert kwargs['env'] == {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}
        return Process()
    monkeypatch.setattr(jobs.subprocess, 'Popen', popen)
    if expected is None:
        with pytest.raises(IdentityError):
            jobs.running_uid(51001)
    else:
        assert jobs.running_uid(51001) == expected


@pytest.mark.parametrize('actor', ['own', 'controller', None])
def test_job_key_attestation_occurs_after_uid_drop_without_controller_environment(capability, monkeypatch, actor):
    from shantytown import actor_identity
    spec, _, _ = capability
    actions = []
    monkeypatch.setattr(jobs, 'drop_identity', lambda _: actions.append('drop'))
    # Replace the environment object, not the real test process environment.
    monkeypatch.setattr(jobs.os, 'environ', {'SSH_AUTH_SOCK': 'controller', 'QUIPU_AUTH_TOKEN': 'fixture'})
    monkeypatch.setattr(jobs.os, 'chdir', lambda home: actions.append(('cwd', home)))
    def authenticate():
        assert actions == ['drop', ('cwd', spec['home'])]
        assert jobs.os.environ == {'HOME': spec['home'], 'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}
        return spec['principal'] if actor == 'own' else actor
    monkeypatch.setattr(actor_identity, 'authenticated_actor', authenticate)
    if actor == 'own':
        jobs.attest_job(spec)
    else:
        with pytest.raises(IdentityError, match='job key'):
            jobs.attest_job(spec)


@pytest.mark.parametrize('fault', ['none', 'missing-plan', 'empty', 'below-minimum', 'wrong-range',
                                   'undeclared', 'missing-manifest', 'changed-digest', 'writable-plan'])
def test_host_plan_pins_exact_slots_range_and_manifest_bytes(capability, fault):
    spec, _, path = capability
    plan_path = jobs.BASE / 'slots.json'
    plan = json.loads(plan_path.read_text())
    if fault == 'missing-plan':
        plan_path.unlink()
    elif fault == 'empty':
        plan['slots'] = {}
    elif fault == 'below-minimum':
        plan['uid_min'] = 9999
    elif fault == 'wrong-range':
        plan['uid_max'] = 51000
    elif fault == 'undeclared':
        plan['slots'] = {'eph-task-000002': plan['slots'][spec['principal']]}
    elif fault == 'missing-manifest':
        path.unlink()
    elif fault == 'changed-digest':
        # Even an innocuous manifest edit requires a reviewed host-plan update.
        path.write_text(path.read_text() + '\n')
    if fault not in ('missing-plan',):
        plan_path.write_text(json.dumps(plan))
    if fault == 'writable-plan':
        plan_path.chmod(0o666)
    if fault == 'none':
        assert jobs.inventory() == [(spec, jobs.load(spec['principal'])[1])]
    else:
        with pytest.raises((IdentityError, OSError)):
            jobs.inventory()


@pytest.mark.parametrize('operation,caller,accepted', [
    ('submit', 'job', True), ('submit', 'controller', False), ('submit', 'other', False),
    ('poll', 'controller', True), ('poll', 'job', False), ('poll', 'other', False),
    ('stop', 'job', False), ('launch', 'job', False), ('check', 'job', False),
])
def test_helper_mailbox_roles_use_protected_uid_not_claims(capability, monkeypatch, operation, caller, accepted):
    import io
    from shantytown import job_mailbox
    spec, _, _ = capability
    digest = jobs.load(spec['principal'])[1]
    caller_uid = {'job': spec['uid'], 'controller': spec['controller_uid'], 'other': 51009}[caller]
    monkeypatch.setattr(jobs.os, 'geteuid', lambda: 0)
    monkeypatch.setenv('SUDO_UID', str(caller_uid))
    monkeypatch.setenv('SHANTY_AGENT', spec['principal'])
    protected = jobs.protected
    monkeypatch.setattr(jobs, 'protected', lambda path, **kw:
                        None if Path(path) == Path(jobs.__file__).absolute()
                        else protected(path, **kw))
    calls = []
    monkeypatch.setattr(jobs, 'check_native', lambda *a, **kw: calls.append('binding'))
    monkeypatch.setattr(jobs.sys, 'stdin', io.TextIOWrapper(io.BytesIO(
        b'{"kind":"report","verdict":"done","summary":"own"}')))
    monkeypatch.setattr(job_mailbox, 'submit', lambda *a, **kw: calls.append('submit'))
    monkeypatch.setattr(job_mailbox, 'read', lambda *a, **kw: calls.append('poll') or {})
    assert jobs.main([operation, spec['principal'], digest]) == (0 if accepted else 1)
    assert calls == (['binding', operation] if accepted else [])


@pytest.mark.parametrize('fault', ['none', 'uid', 'home', 'principal'])
def test_local_job_uses_protected_uid_and_attestation_even_without_markers(capability, monkeypatch, fault):
    from shantytown import actor_identity
    spec, _, _ = capability
    row = {'principal': spec['principal'], 'home': spec['home']}
    monkeypatch.setattr(actor_identity, '_policy', lambda *a, **kw: row)
    monkeypatch.setattr(jobs.os, 'geteuid', lambda: spec['uid'] + (1 if fault == 'uid' else 0))
    if fault == 'home':
        row['home'] = '/synthetic/controller'
    calls = []
    monkeypatch.setattr(actor_identity, 'authenticated_actor',
                        lambda: calls.append('key') or ('boss' if fault == 'principal' else spec['principal']))
    monkeypatch.delenv('SHANTY_AGENT', raising=False)
    if fault == 'none':
        assert jobs.local_job() == (spec, jobs.load(spec['principal'])[1])
        assert calls == ['key']
    else:
        with pytest.raises(IdentityError):
            jobs.local_job()


def test_lifecycle_authorization_does_not_depend_on_job_owned_settings(capability, monkeypatch):
    from shantytown import actor_identity
    spec, _, _ = capability
    digest = jobs.load(spec['principal'])[1]
    jobs.consume(spec, digest)
    row = {'uid': spec['uid'], 'home': spec['home'], 'sd': '/synthetic/immutable/sd'}
    monkeypatch.setattr(actor_identity, '_policy', lambda *a, **kw: row)
    account = SimpleNamespace(pw_name=spec['username'], pw_uid=spec['uid'], pw_gid=spec['gid'],
                              pw_dir=spec['home'], pw_shell='/usr/bin/false')
    monkeypatch.setattr(jobs.pwd, 'getpwnam', lambda _: account)
    monkeypatch.setattr(jobs.pwd, 'getpwall', lambda: [account])
    monkeypatch.setattr(jobs.grp, 'getgrall', lambda: [SimpleNamespace(
        gr_name=spec['username'], gr_gid=spec['gid'], gr_mem=[])])
    original = jobs.protected
    fixed = {row['sd'], spec['argv'][0], spec['root']}
    monkeypatch.setattr(jobs, 'protected', lambda path, **kw:
                        None if str(path) in fixed else original(path, **kw))
    # None of this synthetic job's mutable directories/settings exists. Stop
    # remains authorized by immutable policy/account/receipt, never their mode.
    assert jobs.check_native(spec, consumed_digest=digest, lifecycle=True) == row
    with pytest.raises((OSError, IdentityError)):
        jobs.check_native(spec, consumed_digest=digest)


@pytest.mark.parametrize('fault', ['none', 'foreign-owner', 'wrong-target', 'custom-link', 'linux'])
def test_only_canonical_root_owned_macos_var_alias_is_accepted(monkeypatch, fault):
    import stat
    path = Path('/var/lib/shantytown/fixture.json')
    monkeypatch.setattr(jobs.sys, 'platform', 'linux' if fault == 'linux' else 'darwin')
    def metadata(entry):
        if entry == Path('/var'):
            return SimpleNamespace(st_uid=51001 if fault == 'foreign-owner' else 0,
                                   st_mode=stat.S_IFLNK | 0o777)
        if fault == 'custom-link' and entry == Path('/var/lib'):
            return SimpleNamespace(st_uid=0, st_mode=stat.S_IFLNK | 0o777)
        return SimpleNamespace(st_uid=0, st_mode=(stat.S_IFREG | 0o644) if entry == path else (stat.S_IFDIR | 0o755))
    monkeypatch.setattr(Path, 'lstat', metadata)
    monkeypatch.setattr(jobs.os, 'readlink', lambda _: '/wrong/target' if fault == 'wrong-target' else 'private/var')
    if fault == 'none':
        jobs.protected(path)
    else:
        with pytest.raises(IdentityError):
            jobs.protected(path)


@pytest.mark.parametrize('fault', ['shared-uid', 'shared-gid', 'foreign-member', 'foreign-primary'])
def test_native_uid_or_group_sharing_refuses_even_with_valid_protected_policy(capability, monkeypatch, fault):
    from shantytown import actor_identity
    spec, _, _ = capability
    row = {'uid': spec['uid'], 'home': spec['home'], 'sd': '/synthetic/sd'}
    monkeypatch.setattr(actor_identity, '_policy', lambda *a, **kw: row)
    account = SimpleNamespace(pw_name=spec['username'], pw_uid=spec['uid'], pw_gid=spec['gid'],
                              pw_dir=spec['home'], pw_shell='/usr/bin/false')
    users = [account]
    group = SimpleNamespace(gr_name=spec['username'], gr_gid=spec['gid'], gr_mem=[])
    groups = [group]
    if fault == 'shared-uid':
        users.append(SimpleNamespace(pw_name='other', pw_uid=spec['uid'], pw_gid=51002))
    elif fault == 'shared-gid':
        groups.append(SimpleNamespace(gr_name='other', gr_gid=spec['gid'], gr_mem=[]))
    elif fault == 'foreign-member':
        group.gr_mem = ['other']
    else:
        users.append(SimpleNamespace(pw_name='other', pw_uid=51002, pw_gid=spec['gid']))
    monkeypatch.setattr(jobs.pwd, 'getpwnam', lambda _: account)
    monkeypatch.setattr(jobs.pwd, 'getpwall', lambda: users)
    monkeypatch.setattr(jobs.grp, 'getgrall', lambda: groups)
    original = jobs.protected
    monkeypatch.setattr(jobs, 'protected', lambda path, **kw:
                        None if str(path) == row['sd'] else original(path, **kw))
    with pytest.raises(IdentityError, match='shared'):
        jobs.check_native(spec, lifecycle=True)
