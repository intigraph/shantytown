"""Projection isolation and exact-byte binding through bounded fake transport."""
import copy
import io
import json
from urllib.error import HTTPError, URLError

import pytest

from shantytown import memory_remote as remote
from shantytown.memory_files import MemoryFile, snapshot

OWNER = remote.Owner('urn:example:deploy', 'urn:example:project', 'urn:example:alpha')


def fixture():
    file = MemoryFile('topics/one.md', '\ufeffλ\r\n[link](two.md)\r\n'.encode())
    head = dict(revision='urn:example:r1', sha256=file.sha256, bytes=len(file.data), tombstone=False)
    return dict(authenticated_owner=OWNER.crew, export={
        'format': 'quipu.memory-files/v1', 'coverage': 'this_repository_owner_records',
        'snapshot': dict(owner=OWNER.wire(), revision='urn:example:s1', files={file.path: head}),
        'files': [dict(owner=OWNER.wire(), path=file.path, revision=head['revision'], text=file.data.decode())]})


class Response(io.BytesIO):
    status = 200


class Opener:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if isinstance(self.result, Exception):
            raise self.result
        return Response(json.dumps(self.result).encode())


def test_own_projection_stages_exact_source_without_touching_native_root(tmp_path, monkeypatch):
    monkeypatch.setattr(remote.quipu_auth, 'write_headers', lambda _: {'Authorization': 'Bearer fixture'})
    native = tmp_path / 'native'
    native.mkdir()
    (native / 'MEMORY.md').write_text('external source survives')
    result = fixture()
    opener = Opener(result)
    generation = remote.Client('https://example.test', OWNER, opener=opener).stage_own(tmp_path)
    assert snapshot(generation)[0].data == result['export']['files'][0]['text'].encode()
    assert (native / 'MEMORY.md').read_text() == 'external source survives'
    request, timeout = opener.calls[0]
    assert request.full_url == 'https://example.test/memory/projection'
    assert timeout == 10
    assert len(opener.calls) == 1


@pytest.mark.parametrize('change', ['shared', 'wrong-identity', 'wrong-owner', 'hash', 'size',
                                    'duplicate', 'missing', 'partial', 'path', 'tombstone', 'revision'])
def test_forged_or_incomplete_projection_refused_before_staging(tmp_path, change):
    value = fixture()
    export = value['export']
    file = export['files'][0]
    head = export['snapshot']['files'][file['path']]
    if change == 'shared':
        value.pop('authenticated_owner')
    elif change == 'wrong-identity':
        value['authenticated_owner'] = 'urn:example:beta'
    elif change == 'wrong-owner':
        file['owner'] = dict(OWNER.wire(), crew='urn:example:beta')
    elif change == 'hash':
        file['text'] = 'changed after manifest'
    elif change == 'size':
        head['bytes'] += 1
    elif change == 'duplicate':
        export['files'].append(copy.deepcopy(file))
    elif change == 'missing':
        export['files'].clear()
    elif change == 'partial':
        export['coverage'] = 'partial'
    elif change == 'path':
        export['snapshot']['files']['../escape'] = export['snapshot']['files'].pop(file['path'])
        file['path'] = '../escape'
    elif change == 'revision':
        file['revision'] = 'urn:example:different-revision'
    elif change == 'tombstone':
        head['tombstone'] = True
    with pytest.raises(remote.UnsafeMemory):
        remote.verified_files(value, OWNER)
    assert list(tmp_path.iterdir()) == []


def test_crosscrew_read_stays_public_and_not_a_projection(monkeypatch):
    monkeypatch.setattr(remote.quipu_auth, 'write_headers', lambda _: pytest.fail('public read used credentials'))
    result = dict(coverage='this_repository_owner_records', snapshot=fixture()['export']['snapshot'])
    opener = Opener(result)
    assert remote.Client('https://example.test', OWNER, opener=opener).read() == result['snapshot']
    assert opener.calls[0][0].get_header('Authorization') is None


@pytest.mark.parametrize('error', [URLError('private diagnostic'), TimeoutError('private diagnostic'),
                                  HTTPError('private-url', 409, 'private response', {}, None)])
def test_indeterminate_or_conflict_is_not_retried_or_printed(error):
    opener = Opener(error)
    with pytest.raises(remote.Unproven) as caught:
        remote.Client('https://example.test', OWNER, opener=opener).read()
    assert 'private' not in str(caught.value)
    assert len(opener.calls) == 1


def test_duplicate_json_and_userinfo_origin_refused():
    with pytest.raises(remote.Unproven):
        remote._json('{"receipt":1,"receipt":2}')
    with pytest.raises(remote.Unproven):
        remote.Client('https://user:secret@example.test', OWNER)


def test_selected_identity_is_not_guessed_from_card_alias_or_harness(monkeypatch):
    from shantytown import crew_credentials
    mapping = {'alpha': OWNER.crew, 'renamed-alpha': OWNER.crew, 'beta': 'urn:example:beta'}
    monkeypatch.setattr(crew_credentials, 'selection', lambda root, agent:
                        ({}, {'principal': mapping[agent], 'quipu_cli': {}}) if agent in mapping else None)
    args = ('fixture-root', 'alpha', 'https://example.test', OWNER.deployment, OWNER.project)
    first = remote.Client.for_agent(*args)
    alias = remote.Client.for_agent(args[0], 'renamed-alpha', *args[2:])
    assert first.owner == alias.owner == OWNER
    assert remote.Client.for_agent(args[0], 'beta', *args[2:]).owner != OWNER
    with pytest.raises(remote.Unproven):
        remote.Client.for_agent(args[0], 'not-registered', *args[2:])


def intent():
    return dict(owner=OWNER.wire(), path='MEMORY.md', text='\ufeffλ\r\nexact',
                expected_snapshot=None, expected_file=None, idempotency_key='one',
                harness='fixture', account='selected')


def receipt(request):
    import hashlib
    canonical = remote.canonical_intent(request, OWNER)
    digest = hashlib.sha256(json.dumps(canonical, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    data = (request['text'] or '').encode()
    return dict(owner=OWNER.wire(), path=request['path'], request_hash=digest,
                snapshot='urn:quipu:memory:snapshot:' + digest, committed_at='2026-01-01T00:00:00Z',
                file=dict(revision='urn:quipu:memory:revision:' + digest,
                          sha256=hashlib.sha256(data).hexdigest(), bytes=len(data),
                          tombstone=request['text'] is None))


@pytest.mark.parametrize('mutation', ['owner', 'path', 'intent', 'snapshot', 'revision', 'hash', 'size', 'tombstone'])
def test_commit_receipt_must_bind_exact_intent_and_file(mutation):
    request = intent()
    value = receipt(request)
    if mutation == 'owner': value['owner'] = dict(OWNER.wire(), crew='urn:example:beta')
    elif mutation == 'path': value['path'] = 'different.md'
    elif mutation == 'intent': value['request_hash'] = '0' * 64
    elif mutation == 'snapshot': value['snapshot'] = 'urn:example:other'
    elif mutation == 'revision': value['file']['revision'] = 'urn:example:other'
    elif mutation == 'hash': value['file']['sha256'] = '0' * 64
    elif mutation == 'size': value['file']['bytes'] = True
    elif mutation == 'tombstone': value['file']['tombstone'] = True
    with pytest.raises(remote.Unproven):
        remote.Client('https://example.test', OWNER)._receipt({'receipt': value}, request)


def test_receipt_lookup_is_read_only_and_accepts_absent_or_exact(monkeypatch):
    monkeypatch.setattr(remote.quipu_auth, 'write_headers', lambda _: {'Authorization': 'Bearer fixture'})
    request = intent()
    opener = Opener({'receipt': None})
    client = remote.Client('https://example.test', OWNER, opener=opener)
    assert client.receipt(request) is None
    assert opener.calls[0][0].full_url.endswith('/memory/receipt')
    opener.result = {'receipt': receipt(request)}
    assert client.receipt(request) == opener.result['receipt']
    assert all(call[0].full_url.endswith('/memory/receipt') for call in opener.calls)
