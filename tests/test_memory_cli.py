"""Actual parser/CLI plus isolated command controls; no native selection."""
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys

import pytest

from shantytown import cli, memory_cli as memory
from shantytown.memory_remote import Unproven


def args(tmp_path, action, *extra):
    value = cli._parse_args(['--root', str(tmp_path), 'agent', 'memory', 'alpha', action,
                            '--server', 'https://example.test', '--deployment',
                            'urn:example:deploy', '--project', 'urn:example:project', *extra])
    return value


def test_actual_cli_capabilities_and_inspect_do_not_select_native_root(tmp_path):
    native = tmp_path / 'native'
    native.mkdir()
    source = native / 'MEMORY.md'
    source.write_bytes(b'# Offline\r\n')
    before = source.stat()
    env = dict(os.environ, PYTHONPATH=str(Path(cli.__file__).parent.parent))
    for action, extra in [('capabilities', []), ('inspect', ['--directory', str(native)])]:
        result = subprocess.run([sys.executable, '-m', 'shantytown.cli', '--root',
                                 str(tmp_path), 'agent', 'memory', 'alpha', action, *extra],
                                capture_output=True, text=True, env=env, timeout=20)
        assert result.returncode == 0, result.stderr
        output = json.loads(result.stdout)
        if action == 'capabilities':
            assert output['native_selection'] == 'NOT IMPLEMENTED'
        else:
            assert output['files'][0]['bytes'] == len(source.read_bytes())
            assert output['native_selection'] == 'UNCHANGED'
    after = source.stat()
    assert (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) == (
        before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)


def test_crosscrew_read_is_explicit_historical_and_never_staged(tmp_path, monkeypatch):
    class Reader:
        def __init__(self, server, owner):
            self.owner = owner

        def read(self):
            return {'owner': self.owner.wire(), 'revision': 'urn:example:revision'}
    monkeypatch.setattr(memory, 'Client', Reader)
    result = memory.execute(args(tmp_path, 'read', '--owner', 'urn:example:beta'))
    assert result['historical'] is True
    assert result['owner']['crew'] == 'urn:example:beta'
    assert result['coverage'] == 'this_repository_owner_records'


@pytest.mark.parametrize('action', ['stage', 'commit', 'deliver'])
def test_crosscrew_mutation_or_projection_refuses_before_client_selection(tmp_path, monkeypatch, action):
    monkeypatch.setattr(memory.Client, 'for_agent', lambda *a: pytest.fail('selected writer'))
    with pytest.raises(Unproven):
        memory.execute(args(tmp_path, action, '--owner', 'urn:example:beta'))


def test_missing_scope_refuses_without_guessing_owner(tmp_path):
    value = args(tmp_path, 'read')
    value.project = None
    with pytest.raises(Unproven):
        memory.execute(value)


def test_request_symlink_and_nonprivate_file_refuse(tmp_path):
    path = tmp_path / 'request.json'
    path.write_text('{}')
    path.chmod(0o644)
    with pytest.raises(Unproven):
        memory._request(path)
    path.chmod(0o600)
    assert memory._request(path) == {}
    link = tmp_path / 'link'
    link.symlink_to(path)
    with pytest.raises(OSError):
        memory._request(link)


def test_stage_uses_own_verified_client_without_native_replacement(tmp_path, monkeypatch):
    class Own:
        def stage_own(self, parent):
            assert parent == tmp_path
            return tmp_path / 'exclusive-generation'
    monkeypatch.setattr(memory.Client, 'for_agent', lambda *a: Own())
    result = memory.execute(args(tmp_path, 'stage', '--parent', str(tmp_path)))
    assert result['native_selection'] == 'UNCHANGED'
    assert result['generation'].endswith('exclusive-generation')


def test_failure_diagnostic_does_not_echo_source_or_private_paths(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(memory, 'execute', lambda _: (_ for _ in ()).throw(Unproven('private body')))
    assert memory.command(args(tmp_path, 'read')) == 2
    captured = capsys.readouterr()
    assert 'private body' not in captured.err
    assert captured.out == ''


@pytest.mark.parametrize('lost_reply', [False, True])
def test_commit_command_retains_intent_and_later_delivery_never_duplicates(tmp_path, monkeypatch, lost_reply):
    from shantytown.memory_remote import Client, Owner, canonical_intent
    owner = Owner('urn:example:deploy', 'urn:example:project', 'urn:example:alpha')
    class Remote(Client):
        def __init__(self):
            super().__init__('https://example.test', owner)
            self.accepted = None
            self.writes = 0

        def receipt(self, request):
            return self.accepted

        def commit(self, request):
            self.writes += 1
            digest = hashlib.sha256(json.dumps(canonical_intent(request, owner),
                ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
            data = request['text'].encode()
            self.accepted = dict(owner=owner.wire(), path=request['path'], request_hash=digest,
                snapshot='urn:quipu:memory:snapshot:' + digest,
                file=dict(revision='urn:quipu:memory:revision:' + digest,
                          sha256=hashlib.sha256(data).hexdigest(), bytes=len(data), tombstone=False))
            if lost_reply:
                raise Unproven('lost response after actual accepted fixture commit')
            return self.accepted
    remote = Remote()
    monkeypatch.setattr(memory.Client, 'for_agent', lambda *a: remote)
    root = tmp_path / 'outbox'
    root.mkdir(mode=0o700)
    request = tmp_path / 'request.json'
    request.write_text(json.dumps(dict(owner=owner.wire(), path='MEMORY.md', text='λ\r\n',
        expected_snapshot=None, expected_file=None, idempotency_key='one',
        harness='fixture', account='selected')))
    request.chmod(0o600)
    command = args(tmp_path, 'commit', '--request', str(request), '--outbox', str(root))
    if lost_reply:
        with pytest.raises(Unproven):
            memory.execute(command)
    else:
        assert memory.execute(command)['receipt'] == remote.accepted
    intents = list(root.glob('intent-*.json'))
    intent = next(p.name for p in intents if not p.name.endswith('.receipt.json'))
    assert memory.execute(args(tmp_path, 'deliver', '--intent', intent,
                               '--outbox', str(root)))['receipt'] == remote.accepted
    assert memory.execute(command)['receipt'] == remote.accepted
    assert remote.writes == 1
