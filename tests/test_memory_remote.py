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
    return dict(selected_owner=OWNER.crew, export={
        'format': 'shantytown.memory-files/v1', 'coverage': 'this_repository_owner_records',
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


def test_own_projection_stages_exact_source_without_touching_native_root(tmp_path):
    native = tmp_path / 'native'
    native.mkdir()
    (native / 'MEMORY.md').write_text('external source survives')
    result = fixture()
    generation = remote.stage(remote.verified_files(result, OWNER), tmp_path)
    assert snapshot(generation)[0].data == result['export']['files'][0]['text'].encode()
    assert (native / 'MEMORY.md').read_text() == 'external source survives'


@pytest.mark.parametrize('change', ['shared', 'wrong-identity', 'wrong-owner', 'hash', 'size',
                                    'duplicate', 'missing', 'partial', 'path', 'tombstone', 'revision'])
def test_forged_or_incomplete_projection_refused_before_staging(tmp_path, change):
    value = fixture()
    export = value['export']
    file = export['files'][0]
    head = export['snapshot']['files'][file['path']]
    if change == 'shared':
        value.pop('selected_owner')
    elif change == 'wrong-identity':
        value['selected_owner'] = 'urn:example:beta'
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


def test_read_export_empty_is_explicit_coverage_but_not_a_native_projection():
    value = {'format': 'shantytown.memory-files/v1', 'coverage': 'this_repository_owner_records',
             'snapshot': None, 'files': []}
    assert remote._export_files(value, OWNER, allow_empty=True) == ()
    with pytest.raises(remote.Unproven):
        remote.verified_files({'selected_owner': OWNER.crew, 'export': value}, OWNER)
    value['coverage'] = 'partial'
    with pytest.raises(remote.Unproven):
        remote._export_files(value, OWNER, allow_empty=True)


def test_query_result_count_and_excerpt_are_bounded_and_explicit():
    value = fixture()['export']
    original = value['files'][0]
    value['files'] = []
    value['snapshot']['files'] = {}
    for n in range(3):
        file = MemoryFile(f'topics/{n}.md', ('needle' + 'x' * 1800).encode())
        head = dict(revision=f'urn:example:r{n}', sha256=file.sha256,
                    bytes=len(file.data), tombstone=False)
        value['snapshot']['files'][file.path] = head
        value['files'].append(dict(original, path=file.path, revision=head['revision'], text=file.data.decode()))
    client = remote.Client('https://example.test', OWNER, opener=Opener(value))
    client.export = lambda: value
    result = client.query('needle', limit=1)
    assert result['truncated'] is True
    assert len(result['matches']) == 1
    assert len(result['matches'][0]['excerpt']) == 1600
    assert result['matches'][0]['excerpt_truncated'] is True
    assert 'selected owner only' in result['search']
    with pytest.raises(remote.Unproven):
        client.query('')


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


def test_named_client_uses_selected_cli_identity_not_callers_ambient_token(monkeypatch, tmp_path):
    from shantytown import crew_credentials
    monkeypatch.setattr(crew_credentials, 'selection', lambda *a: ({},
        dict(principal=OWNER.crew, quipu_cli={})))
    selected = []
    monkeypatch.setattr(crew_credentials, 'cli_token', lambda root, agent, path:
        selected.append((root, agent, path)) or 'synthetic-selected-token')
    monkeypatch.setattr(remote.quipu_auth, 'status', lambda _: 'enabled')
    monkeypatch.setattr(remote.quipu_auth, 'write_headers', lambda _: pytest.fail('ambient identity used'))
    # The transport fixture returns a named owner projection; no real credential
    # provider, network or runtime path is read by this control.
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self, _): return json.dumps(dict(selected_owner=OWNER.crew,
            export=dict(format='shantytown.memory-files/v1', coverage='this_repository_owner_records',
                        snapshot=None, files=[]))).encode()
    class Opener:
        def open(self, request, timeout):
            assert request.get_header('Authorization') == 'Bearer synthetic-selected-token'
            return Response()
    client = remote.Client.for_agent(tmp_path, 'alpha', 'https://example.test',
                                     OWNER.deployment, OWNER.project, opener=Opener())
    client._request('/update', {'update': 'fixture'}, identity=True)
    assert len(selected) == 1 and selected[0][1] == 'alpha'
    assert selected[0][2].endswith('/shantytown-credentials/alpha/quipu-cli')
    monkeypatch.setattr(remote.quipu_auth, 'status', lambda _: 'writes-disabled')
    with pytest.raises(remote.quipu_auth.CredentialRefused):
        client._request('/update', {'update': 'fixture'}, identity=True)
    assert len(selected) == 1  # No refresh or second credential after refusal.
