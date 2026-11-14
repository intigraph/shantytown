"""Real RDF/SPARQL execution through ordinary-only transport; no live service."""
import io
import json
import threading
from urllib.parse import parse_qs
from urllib.error import URLError

import pytest
from rdflib import Dataset, URIRef

from shantytown import memory_graph as graph, memory_remote as remote
from shantytown.memory_files import MemoryFile, snapshot
from shantytown.memory_outbox import Outbox
from shantytown import memory_batch as batch, memory_sync as sync

OWNER = remote.Owner('urn:example:deployment', 'urn:example:project', 'urn:example:alpha')


class Response(io.BytesIO):
    status = 200


class Ordinary:
    """Execute actual SPARQL, not a mock that interprets the client's intent."""
    def __init__(self):
        self.store = Dataset()
        self.calls = []
        self.lock = threading.RLock()
        self.writes = 0
        self.lose = False
        self.before_update = None
        self.change_result = lambda result: result

    def open(self, request, timeout):
        path = request.full_url.removeprefix('https://example.test')
        self.calls.append((path, request))
        assert timeout == 10
        assert path in {'/query', '/update'}, 'obsolete or invented endpoint'
        with self.lock:
            if path == '/query':
                body = json.loads(request.data)
                result = self.store.query(body['query'])
                rows = [{str(k): str(v) for k, v in row.asdict().items()} for row in result]
                value = dict(rows=rows, count=len(rows), truncated=False)
            else:
                assert request.get_header('Authorization') == 'Bearer synthetic-selected'
                assert request.get_header('X-quipu-purpose') == 'INGEST'
                form = parse_qs(request.data.decode())
                assert set(form) == {'update', 'actor', 'source'}
                if self.before_update:
                    callback, self.before_update = self.before_update, None
                    callback()
                before = set(self.store.quads())
                self.store.update(form['update'][0])
                after = set(self.store.quads())
                new, removed = after - before, before - after
                if new or removed:
                    self.writes += 1
                contexts = {str(q[3]) for q in new | removed}
                value = dict(tx=self.writes if new or removed else None,
                             asserted=len(new), retracted=len(removed),
                             graphs=[dict(graph=g, tx=self.writes) for g in contexts])
                if self.lose:
                    self.lose = False
                    raise URLError('synthetic lost response AFTER committed ordinary update')
            return Response(json.dumps(self.change_result(value)).encode())


@pytest.fixture
def selected(monkeypatch, tmp_path):
    from shantytown import crew_credentials, quipu
    monkeypatch.setattr(crew_credentials, 'selection', lambda root, agent:
        ({}, dict(principal=OWNER.crew if agent == 'alpha' else 'urn:example:beta', quipu_cli={})))
    monkeypatch.setattr(crew_credentials, 'cli_token', lambda *a: 'synthetic-selected')
    monkeypatch.setattr(remote.quipu_auth, 'status', lambda _: 'enabled')
    monkeypatch.setattr(quipu, 'resolve_onto', lambda **_: 'urn:example:ontology:')
    ordinary = Ordinary()
    def make(agent='alpha'):
        return remote.Client.for_agent(tmp_path, agent, 'https://example.test',
            OWNER.deployment, OWNER.project, opener=ordinary)
    return ordinary, make


def intent(owner=OWNER, **changes):
    return dict(dict(owner=owner.wire(), path='MEMORY.md', text='\ufeffλ\r\n[topic](topic.md)\r\n',
        expected_snapshot=None, expected_file=None, idempotency_key='one', harness='fixture',
        account='selected'), **changes)


def test_exact_two_owner_roundtrip_query_and_non_destructive_staging(selected, tmp_path):
    store, make = selected
    alpha, beta = make(), make('beta')
    receipt = alpha.commit(intent())
    beta.commit(intent(beta.owner, text='beta-private'))
    assert alpha.receipt(intent()) == receipt
    assert alpha.read()['revision'] == receipt['snapshot']
    public = remote.Client('https://example.test', OWNER, opener=store)
    assert public.query('λ')['matches'][0]['historical'] is True
    assert public.query('beta-private')['matches'] == []
    native = tmp_path / 'native'
    native.mkdir()
    (native / 'MEMORY.md').write_bytes(b'unsynced external edit')
    generation = alpha.stage_own(tmp_path)
    assert snapshot(generation)[0].data == intent()['text'].encode()
    assert (native / 'MEMORY.md').read_bytes() == b'unsynced external edit'
    assert alpha.projection()['selected_owner'] == OWNER.crew
    assert 'authenticated_owner' not in alpha.projection()
    assert all(path in {'/query', '/update'} for path, _ in store.calls)
    with pytest.raises(remote.Unproven):
        public.projection()
    with pytest.raises(remote.Unproven):
        public.commit(intent())


def test_lost_reply_replays_before_stale_parent_and_no_revision_churn(selected, tmp_path):
    store, make = selected
    client = make()
    root = tmp_path / 'outbox'
    root.mkdir(mode=0o700)
    outbox = Outbox(root, OWNER)
    name = outbox.enqueue(intent())
    store.lose = True
    with pytest.raises(remote.Unproven):
        outbox.deliver(name, client)
    assert store.writes == 1
    receipt = outbox.deliver(name, client)
    assert receipt == client.commit(intent())
    assert store.writes == 1
    stamps = {p.name: p.stat().st_mtime_ns for p in root.iterdir()}
    assert outbox.deliver(name, client) == receipt
    assert stamps == {p.name: p.stat().st_mtime_ns for p in root.iterdir()}
    with pytest.raises(remote.Unproven):
        client.commit(intent(text='different content same key'))
    assert store.writes == 1


def test_cas_race_between_read_and_atomic_update_preserves_winner(selected):
    store, make = selected
    first, second = make(), make()
    store.before_update = lambda: second.commit(intent(text='winner', idempotency_key='winner'))
    with pytest.raises(remote.Unproven):
        first.commit(intent())
    assert first.export()['files'][0]['text'] == 'winner'
    assert first.receipt(intent()) is None
    assert store.writes == 1


def test_multifile_sync_is_exact_and_nochange_does_not_write(selected, tmp_path):
    store, make = selected
    root = tmp_path / 'outbox'
    root.mkdir(mode=0o700)
    outbox, client = Outbox(root, OWNER), make()
    files = (MemoryFile('MEMORY.md', b'[topic](topic.md)\r\n'), MemoryFile('topic.md', 'λ\r\n'.encode()))
    assert sync.step(outbox, client, lambda: files, harness='fixture', account='selected')['status'] == 'pending'
    assert sync.step(outbox, client, lambda: pytest.fail('recaptured active batch'), harness='fixture', account='selected')['status'] == 'accepted'
    assert store.writes == 2
    assert remote.verified_files(client.projection(), OWNER) == files
    assert sync.step(outbox, client, lambda: files, harness='fixture', account='selected')['status'] == 'unchanged'
    assert store.writes == 2
    with pytest.raises(remote.Unproven):
        batch.plan(OWNER, files[:1], client.projection(), harness='fixture', account='selected')


@pytest.mark.parametrize('damage', ['truncated', 'missing-count', 'wrong-count', 'missing-rows'])
def test_partial_query_never_becomes_empty_success(selected, damage):
    store, make = selected
    def changed(value):
        if damage == 'truncated': value['truncated'] = True
        elif damage == 'wrong-count': value['count'] += 1
        else: value.pop('count' if damage == 'missing-count' else 'rows')
        return value
    store.change_result = changed
    with pytest.raises(remote.Unproven):
        make().export()
    assert store.writes == 0


@pytest.mark.parametrize('damage', ['tx', 'asserted', 'conforms', 'graphs'])
def test_http200_does_not_prove_update_or_allow_unverified_receipt(selected, damage):
    store, make = selected
    def changed(value):
        if 'graphs' in value:
            value[damage] = {'tx': None, 'asserted': 0, 'conforms': False, 'graphs': []}[damage]
        return value
    store.change_result = changed
    client = make()
    with pytest.raises(remote.Unproven):
        client.commit(intent())
    # The write may have committed: readback on the next invocation, never replay blindly.
    assert store.writes == 1
    assert client.receipt(intent()) is not None


def test_tombstone_and_stale_expected_file_preserve_all_history(selected):
    store, make = selected
    client = make()
    first = client.commit(intent())
    second = intent(text=None, expected_snapshot=first['snapshot'],
        expected_file=first['file']['revision'], idempotency_key='delete')
    client.commit(second)
    assert remote.verified_files(client.projection(), OWNER) == ()
    assert client.receipt(intent()) == first
    with pytest.raises(remote.Unproven):
        client.commit(intent(idempotency_key='stale'))
    assert store.writes == 2


def test_graph_injection_and_missing_shape_namespace_refuse(selected, monkeypatch):
    store, make = selected
    with pytest.raises(remote.Unproven):
        remote.Owner('urn:ok', 'urn:ok', 'urn:evil> } INSERT {')
    from shantytown import quipu
    monkeypatch.setattr(quipu, 'resolve_onto', lambda **_: quipu.DEFAULT_ONTO)
    with pytest.raises(remote.Unproven):
        make().commit(intent())
    assert store.writes == 0


def test_changed_selected_owner_refuses_before_any_own_operation(selected, monkeypatch):
    store, make = selected
    client = make()
    from shantytown import crew_credentials
    monkeypatch.setattr(crew_credentials, 'selection', lambda *a:
        ({}, dict(principal='urn:example:other', quipu_cli={})))
    for operation in (lambda: client.commit(intent()), client.projection, lambda: client.receipt(intent())):
        with pytest.raises(remote.Unproven):
            operation()
    assert store.calls == []


@pytest.mark.parametrize('damage', ['missing-record', 'changed-intent', 'wrong-owner', 'ambiguous-head'])
def test_corrupt_current_graph_never_stages_native_data(selected, tmp_path, damage):
    from rdflib import Literal
    store, make = selected
    client = make()
    receipt = client.commit(intent())
    g = client._graph()
    context = store.store.graph(URIRef(g.graph))
    revision = URIRef(receipt['file']['revision'])
    predicate = URIRef(graph.RDFS + 'comment')
    if damage == 'ambiguous-head':
        context.add((URIRef(g.collection), URIRef(graph.RDFS + 'seeAlso'), URIRef('urn:example:foreign')))
    elif damage == 'missing-record':
        context.remove((revision, predicate, None))
    else:
        record = json.loads(str(next(context.objects(revision, predicate))))
        if damage == 'changed-intent': record['intent']['text'] = 'corrupt'
        else: record['intent']['owner']['crew'] = 'urn:example:foreign'
        context.set((revision, predicate, Literal(json.dumps(record))))
    with pytest.raises(remote.Unproven):
        client.stage_own(tmp_path)
    assert list(tmp_path.iterdir()) == []
