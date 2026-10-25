import hashlib
import json
import os
import subprocess

import pytest

from shantytown import advise_signing as signing


@pytest.fixture
def profile(tmp_path, monkeypatch):
    root = tmp_path / 'profile'
    root.mkdir(mode=0o700)
    (root / 'seeds').mkdir(mode=0o700)
    config = root / 'seeds/config.toml'
    config.write_text('[quipu]\nsigning_key_file="/synthetic/key"\n'
                      'signing_session="synthetic-session"\nsigning_introducer="lead"\n'
                      'require_identity=false\nactor_principal_mode="observe"\n')
    config.chmod(0o600)
    policy = tmp_path / 'policy.json'
    policy.write_text(json.dumps({'version': 1, 'mode': 'advise', 'profiles': {
        'worker': {'config_dir': str(root),
                   'config_sha256': hashlib.sha256(config.read_bytes()).hexdigest()}}}))
    policy.chmod(0o600)
    monkeypatch.setattr(signing, 'POLICY_PATH', policy)
    monkeypatch.setattr(signing, 'POLICY_OWNER', os.geteuid())
    return root, policy


def identity(principal='worker'):
    return json.dumps({'authenticated': True, 'auth_class': 'attested_session',
                       'principal': principal, 'session': 'synthetic-session',
                       'key_id': 'sha256:' + 'a' * 64})


@pytest.mark.parametrize('args,expected', [
    (['show', 'item'], False), (['comments', 'list', 'item'], False),
    (['comments', 'add', 'item'], True), (['--actor=operator', 'update', 'item'], True),
    (['--actor', 'operator', 'comments', 'add', 'item'], True),
    (['--json', 'close', 'item'], True), (['--actor'], False)])
def test_mutation_classification_preserves_reads(args, expected):
    assert signing.mutation(args) is expected


def invoke(runner, *, asserted='worker'):
    return signing.run(['sd', 'create', 'synthetic'], actor='worker',
                       asserted_actor=asserted, identity_command=['sd', 'identity', '--json'],
                       options={'env': {'KEEP': 'original'}, 'timeout': 20,
                                'capture_output': True, 'text': True}, runner=runner)


def test_absent_policy_is_exact_original_single_call(tmp_path, monkeypatch):
    monkeypatch.setattr(signing, 'POLICY_PATH', tmp_path / 'absent')
    calls = []
    def run(cmd, **opts):
        calls.append((cmd, opts))
        return subprocess.CompletedProcess(cmd, 0)
    invoke(run)
    assert len(calls) == 1
    assert calls[0][1]['env'] == {'KEEP': 'original'}


@pytest.mark.parametrize('principal,asserted,match', [
    ('worker', 'worker', True), ('other', 'worker', False), ('worker', 'operator', False)])
def test_records_actual_verified_principal_and_explicit_claim(profile, principal, asserted, match):
    root, _ = profile
    calls = []
    def run(cmd, **opts):
        calls.append((cmd, opts))
        assert opts['env'] == {'KEEP': 'original', 'XDG_CONFIG_HOME': str(root)}
        return subprocess.CompletedProcess(cmd, 0, identity(principal) if cmd[1] == 'identity' else '')
    assert invoke(run, asserted=asserted).returncode == 0
    assert len(calls) == 2
    event = json.loads((root / 'writes.jsonl').read_text())
    assert (event['actor'], event['principal'], event['match']) == (asserted, principal, match)
    assert event['command_exit'] == 0 and event['selection'] == 'profile'
    assert (root / 'writes.jsonl').stat().st_mode & 0o777 == 0o600


def test_unavailable_preflight_preserves_original_before_one_mutation(profile):
    root, _ = profile
    mutations = []
    def run(cmd, **opts):
        if cmd[1] == 'identity':
            raise subprocess.TimeoutExpired(cmd, 10)
        mutations.append(opts)
        return subprocess.CompletedProcess(cmd, 0)
    invoke(run)
    assert len(mutations) == 1 and mutations[0]['env'] == {'KEEP': 'original'}
    event = json.loads((root / 'writes.jsonl').read_text())
    assert event['selection'] == 'legacy' and not event['authenticated'] and not event['match']


def test_failed_mutation_never_retried_with_original_credentials(profile):
    root, _ = profile
    mutations = []
    def run(cmd, **opts):
        if cmd[1] == 'identity':
            return subprocess.CompletedProcess(cmd, 0, identity())
        mutations.append(opts)
        return subprocess.CompletedProcess(cmd, 2, '', 'synthetic refusal')
    assert invoke(run).returncode == 2
    assert len(mutations) == 1
    assert json.loads((root / 'writes.jsonl').read_text())['command_exit'] == 2


@pytest.mark.parametrize('change', ['hash', 'mode', 'symlink', 'fifo', 'scalar'])
def test_unqualified_profile_cannot_change_original_writer(profile, change, capsys):
    root, policy = profile
    if change == 'hash':
        (root / 'seeds/config.toml').write_text('changed')
    elif change == 'scalar':
        config = root / 'seeds/config.toml'
        config.write_text('quipu = "not-a-table"')
        value = json.loads(policy.read_text())
        value['profiles']['worker']['config_sha256'] = hashlib.sha256(config.read_bytes()).hexdigest()
        policy.write_text(json.dumps(value))
    elif change == 'mode':
        policy.chmod(0o666)
    elif change == 'symlink':
        policy.rename(policy.with_suffix('.saved'))
        policy.symlink_to(policy.with_suffix('.saved'))
    else:
        policy.unlink()
        os.mkfifo(policy)
    calls = []
    def run(cmd, **opts):
        calls.append(opts)
        return subprocess.CompletedProcess(cmd, 0)
    invoke(run)
    assert len(calls) == 1 and calls[0]['env'] == {'KEEP': 'original'}
    assert 'UNKNOWN' in capsys.readouterr().err


def test_unwritable_audit_does_not_change_success_or_retry(profile, monkeypatch, capsys):
    root, _ = profile
    (root / 'writes.jsonl').symlink_to(root / 'untouched')
    calls = []
    def run(cmd, **opts):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, identity() if cmd[1] == 'identity' else '')
    assert invoke(run).returncode == 0 and len(calls) == 2
    assert not (root / 'untouched').exists()
    assert 'not retried' in capsys.readouterr().err


def test_explicit_empty_child_environment_never_inherits_parent_secrets(profile, monkeypatch):
    monkeypatch.setenv('SYNTHETIC_SECRET', 'must-not-inherit')
    def run(cmd, **opts):
        assert 'SYNTHETIC_SECRET' not in opts['env']
        return subprocess.CompletedProcess(cmd, 0, identity() if 'identity' in cmd else '')
    signing.run(['sd', 'create', 'synthetic'], actor='worker', asserted_actor='worker',
                identity_command=['sd', 'identity', '--json'],
                options={'env': {}, 'timeout': 20}, runner=run)


def test_enforcing_profile_is_rejected_even_with_correct_hash(profile, capsys):
    root, policy = profile
    cfg = root / 'seeds/config.toml'
    cfg.write_text(cfg.read_text().replace('require_identity=false', 'require_identity=true'))
    p = json.loads(policy.read_text())
    p['profiles']['worker']['config_sha256'] = hashlib.sha256(cfg.read_bytes()).hexdigest()
    policy.write_text(json.dumps(p))
    calls = []
    def run(cmd, **opts):
        calls.append(cmd)
        assert opts['env'] == {'KEEP': 'original'}
        return subprocess.CompletedProcess(cmd, 0)
    invoke(run)
    assert len(calls) == 1 and 'UNKNOWN' in capsys.readouterr().err


@pytest.mark.real_store
def test_real_seeds_adapter_selects_only_write_child(profile, monkeypatch):
    from shantytown.sd import SdTracker
    monkeypatch.setenv('SHANTY_AGENT', 'worker')
    monkeypatch.setattr('shantytown.actor_identity.authenticated_actor', lambda: None)
    monkeypatch.setattr(SdTracker, 'prove_store', lambda self: None)
    monkeypatch.setattr('shantytown.sd.sdk_subprocess_options',
                        lambda **kw: {'env': {'XDG_CONFIG_HOME': '/synthetic/original'}})
    seen = []
    def run(cmd, **opts):
        seen.append((cmd, opts))
        return subprocess.CompletedProcess(cmd, 0, identity() if 'identity' in cmd else '')
    monkeypatch.setattr('shantytown.sd.subprocess.run', run)
    tracker = SdTracker(quipu='http://example.invalid', prefix='test')
    tracker._bd_in(None, 'show', 'synthetic')
    assert len(seen) == 1
    assert seen[0][1]['env']['XDG_CONFIG_HOME'] == '/synthetic/original'
    tracker._bd_in(None, '--actor=operator', 'comments', 'add', 'synthetic', '--text', 'body')
    assert len(seen) == 3
    event = json.loads((profile[0] / 'writes.jsonl').read_text())
    assert event['actor'] == 'operator' and event['principal'] == 'worker' and not event['match']
