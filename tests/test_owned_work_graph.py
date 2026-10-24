"""Lifecycle observations are not identity or native process liveness."""
import json
from pathlib import Path
import re

import pytest

from shantytown import owned_work_graph as graph
from shantytown.owned_work import OwnedWork


class Registry:
    onto = 'https://example.test/ontology/'

    def __init__(self):
        self.rows = {}
        self.writes = []
        self.read = None
        self.lost = False
        self.head_sets = []

    @property
    def facts(self):
        return [x for x in self.writes if 'owned-work-head-' not in x]

    def set_comment(self, iri, payload):
        self.head_sets.append(json.loads(payload))
        self.rows[iri] = [dict(payload=payload)]

    def _query(self, query):
        if self.read:
            self.read()
        iri = re.search(r'WHERE \{ <([^>]+)>', query).group(1)
        return self.rows.get(iri, [])

    def _knot(self, turtle):
        self.writes.append(turtle)
        iri = re.match(r'<([^>]+)>', turtle).group(1)
        literal = re.search(re.escape('<' + graph.RDFS + 'comment>') +
                            r' ("(?:\\.|[^"\\])*")', turtle).group(1)
        payload = json.loads(literal)
        self.rows[iri] = [dict(payload=payload, revision=json.loads(payload)['revision'])]
        if self.lost:
            raise TimeoutError('ACK lost after commit')


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(graph, '_set_comment', lambda registry, iri, payload: registry.set_comment(iri, payload))
    service = OwnedWork(tmp_path)
    service.launch('worker', now=100)
    return tmp_path, service, Registry()


def test_default_off_and_no_inherited_truth(monkeypatch):
    monkeypatch.delenv('SHANTY_OWNED_WORK_PUBLISH', raising=False)
    assert not graph.enabled()
    monkeypatch.setenv('SHANTY_OWNED_WORK_PUBLISH', '1')
    assert graph.enabled()


def test_lifecycle_revision_survives_heartbeat_and_backwards_stop(world):
    root, service, registry = world
    before = graph.fact('worker', service.snapshot()['worker'], registry.onto, graph.producer(service.root))
    service.heartbeat('worker', now=200)
    assert graph.fact('worker', service.snapshot()['worker'], registry.onto, graph.producer(service.root)) == before
    service.stop('worker', at=90, reason='secret command and private path')
    first = service.snapshot()['worker']
    assert first['graph_revision'] == 2 and first['state'] == 'stopped'
    service.stop('worker', at=500)
    assert service.snapshot()['worker']['graph_revision'] == 2
    fact = graph.fact('worker', first, registry.onto, graph.producer(service.root))
    assert 'secret' not in fact[2] and 'private path' not in fact[2]
    assert 'CrewMember' not in fact[2] and 'crewStatus' not in fact[2]
    service.launch('worker', now=80)
    assert service.snapshot()['worker']['graph_revision'] == 3


def test_exact_readback_and_receipt_suppress_repeat(world):
    root, service, registry = world
    assert len(graph.flush(root, registry)) == 1
    assert graph.flush(root, registry) == [] and len(registry.facts) == 1
    receipts = json.loads((service.root / 'graph-receipts.json').read_text())
    assert receipts['worker']['revision'] == 1


def test_unreachable_read_never_authorizes_write(world):
    root, service, registry = world
    registry.read = lambda: (_ for _ in ()).throw(TimeoutError('unavailable'))
    with pytest.raises(TimeoutError):
        graph.flush(root, registry)
    assert not registry.writes


def test_lost_commit_ack_reconciles_without_resend(world):
    root, service, registry = world
    registry.lost = True
    with pytest.raises(TimeoutError):
        graph.flush(root, registry)
    registry.lost = False
    assert len(graph.flush(root, registry)) == 1
    assert len(registry.facts) == 1


def test_changed_or_ambiguous_remote_fact_refuses(world):
    root, service, registry = world
    iri, payload, _ = graph.fact('worker', service.snapshot()['worker'], registry.onto, graph.producer(service.root))
    registry.rows[iri] = [dict(payload=payload, revision=1), dict(payload='changed', revision=1)]
    with pytest.raises(ValueError, match='ambiguous'):
        graph.flush(root, registry)
    assert not registry.writes


def test_launch_during_read_fences_old_stop(world):
    root, service, registry = world
    service.stop('worker', at=110)
    def relaunch():
        registry.read = None
        service.launch('worker', now=120)
    registry.read = relaunch
    assert graph.flush(root, registry) == [] and not registry.writes
    graph.flush(root, registry)
    payload = next(iter(registry.rows.values()))[0]['payload']
    assert json.loads(payload)['state'] == 'live' and json.loads(payload)['revision'] == 3


def test_legacy_heartbeat_is_versioned_without_renewing_its_observation_time(tmp_path):
    service = OwnedWork(tmp_path)
    service.heartbeat('worker', now=100)
    registry = Registry()
    assert len(graph.flush(tmp_path, registry)) == 1
    _, head = graph._head(registry, graph.producer(service.root))
    assert head['agents'][0]['observed_at'] == 100
    assert head['agents'][0]['revision'] == 1


def test_record_does_not_use_decision_or_workflow_state_fields(world):
    _, service, registry = world
    service.stop('worker', at=200, ceiling=True)
    _, payload, turtle = graph.fact('worker', service.snapshot()['worker'], registry.onto, 'urn:fixture')
    assert json.loads(payload)['state'] == 'ceiling'
    assert 'OperationalFact' in turtle and 'reviewAfter' in turtle
    assert 'expiresAt' not in turtle and 'currentState' not in turtle and 'forTarget' not in turtle


def test_corrupt_receipt_fails_without_erasing_it(world):
    root, service, registry = world
    receipt = service.root / 'graph-receipts.json'
    receipt.write_text('{')
    with pytest.raises(ValueError):
        graph.flush(root, registry)
    assert receipt.read_text() == '{' and not registry.writes


def test_writer_revision_is_global_and_not_reused_after_missing_state(world):
    root, service, registry = world
    service.launch('other', now=101)
    assert service.snapshot()['other']['graph_revision'] == 2
    service.heartbeat('worker', now=500)
    assert service.snapshot()['worker']['graph_revision'] == 3
    service.stop('other', at=90)
    assert service.snapshot()['other']['graph_revision'] == 4
    # Losing state cannot reuse the persisted writer counter; ordinary code
    # never deletes it, and this deliberate private corruption is a control.
    (service.root / 'state.json').unlink()
    service.launch('worker', now=80)
    assert service.snapshot()['worker']['graph_revision'] == 5


def test_late_heartbeat_never_revives_stop_or_changes_its_fact(world):
    root, service, registry = world
    service.stop('worker', at=110)
    before = graph.fact('worker', service.snapshot()['worker'], registry.onto, 'urn:fixture')
    service.heartbeat('worker', now=9000)
    assert graph.fact('worker', service.snapshot()['worker'], registry.onto, 'urn:fixture') == before


def test_two_concurrent_publishers_cannot_overwrite_new_head_with_old(world):
    import threading
    root, service, registry = world
    graph.flush(root, registry)
    service.stop('worker', at=200)
    entered, release = threading.Event(), threading.Event()
    original = registry._query
    failures = []
    def pause_head_read(query):
        if 'SELECT ?payload WHERE' in query and not entered.is_set():
            entered.set()
            assert release.wait(5)
        return original(query)
    registry._query = pause_head_read
    def first_writer():
        try:
            graph.flush(root, registry)
        except BaseException as exc:
            failures.append(exc)
    thread = threading.Thread(target=first_writer)
    thread.start()
    assert entered.wait(5)
    # Heartbeat/state lock stays available while the separate graph lock owns
    # network delivery. This newer writer cannot pass the older writer's lock.
    service.launch('worker', now=300)
    assert graph.flush(root, registry) == []
    release.set()
    thread.join(5)
    assert not thread.is_alive() and not failures
    graph.flush(root, registry)
    heads = registry.head_sets
    assert [x['revision'] for x in heads] == sorted({x['revision'] for x in heads})
    latest = heads[-1]
    assert latest['complete'] and latest['agents'][0]['state'] == 'live'
    assert latest['agents'][0]['revision'] == 3
    # A retained older local state cannot roll back the authenticated head.
    with service.locked() as states:
        states['worker'].update(graph_revision=1, state='stopped')
    with pytest.raises(ValueError, match='replay refused'):
        graph.flush(root, registry)
    assert registry.head_sets[-1] == latest


def test_head_from_another_source_host_is_refused(world):
    root, service, registry = world
    graph.flush(root, registry)
    iri, head = graph._head(registry, graph.producer(service.root))
    head['host'] = 'other-source-host'
    registry.rows[iri] = [dict(payload=json.dumps(head))]
    service.stop('worker', at=200)
    with pytest.raises(ValueError, match='another source host'):
        graph.flush(root, registry)
    assert not registry.head_sets


@pytest.mark.parametrize('fault', ['missing', 'older', 'same-version-changed'])
def test_durable_head_receipt_refuses_receiver_rollback(world, fault):
    root, service, registry = world
    graph.flush(root, registry)
    iri, first = graph._head(registry, graph.producer(service.root))
    service.stop('worker', at=200)
    graph.flush(root, registry)
    before = len(registry.head_sets)
    if fault == 'missing':
        del registry.rows[iri]
    elif fault == 'older':
        registry.rows[iri] = [dict(payload=json.dumps(first))]
    else:
        _, current = graph._head(registry, graph.producer(service.root))
        current['complete'] = False
        registry.rows[iri] = [dict(payload=json.dumps(current))]
    with pytest.raises(ValueError, match='previously observed'):
        graph.flush(root, registry)
    assert len(registry.head_sets) == before


def test_corrupt_durable_head_receipt_never_authorizes_reset(world):
    root, service, registry = world
    graph.flush(root, registry)
    (service.root / 'graph-head.json').write_text('null')
    with pytest.raises(ValueError, match='receipt malformed'):
        graph.flush(root, registry)


def test_root_config_enables_existing_hooks_without_relaunching_agents(tmp_path, monkeypatch):
    monkeypatch.delenv('SHANTY_OWNED_WORK_PUBLISH', raising=False)
    (tmp_path / 'shantytown.toml').write_text('[env]\nSHANTY_OWNED_WORK_PUBLISH = "1"\n')
    assert graph.enabled(tmp_path)
    monkeypatch.setenv('SHANTY_OWNED_WORK_PUBLISH', '0')
    assert not graph.enabled(tmp_path)


def test_local_lease_expiry_advances_graph_revision_without_fresh_liveness(world):
    from types import SimpleNamespace
    from shantytown.answer import Answer
    root, service, registry = world
    graph.flush(root, registry)
    before = service.snapshot()['worker']
    cards = SimpleNamespace(get=lambda name: SimpleNamespace(reports_to='lead'))
    inbox = SimpleNamespace(unread=lambda name: [])
    service.tick(cards, lambda name: Answer.complete_read([], how='empty private owner scope'),
                 inbox, now=before['expires_at'])
    state = service.snapshot()['worker']
    assert state['state'] == 'expired'
    assert state['graph_revision'] > before['graph_revision']
    assert state['graph_observed_at'] == before['graph_observed_at']
    graph.flush(root, registry)
    head = graph._head(registry, graph.producer(service.root))[1]
    assert head['agents'][0]['state'] == 'expired'
    assert head['agents'][0]['revision'] == state['graph_revision']
    assert head['agents'][0]['observed_at'] == before['graph_observed_at']


@pytest.fixture
def published_pair(world):
    root, service, registry = world
    service.launch('other', now=101)
    graph.flush(root, registry)
    old_state = service.snapshot()['worker']
    receipts = service.root / 'graph-receipts.json'
    old_receipt = json.loads(receipts.read_text())['worker']
    service.stop('worker', at=110)
    service.heartbeat('other', now=500)
    graph.flush(root, registry)
    return root, service, registry, old_state, old_receipt


@pytest.mark.parametrize('partial_first', [False, True])
def test_other_agent_max_cannot_mask_replayed_state_and_receipt(published_pair, partial_first):
    root, service, registry, old_state, old_receipt = published_pair
    source = graph.producer(service.root)
    with service.locked() as states:
        states['worker'] = old_state
    if partial_first:
        # A state-only replay remains explicitly partial. Its omission must not
        # erase the published stop's fence before the old receipt is replayed.
        graph.flush(root, registry)
        partial = graph._head(registry, source)[1]
        assert not partial['complete']
        assert all(entry['agent'] != 'worker' for entry in partial['agents'])
    receipt_file = service.root / 'graph-receipts.json'
    receipts = json.loads(receipt_file.read_text())
    receipts['worker'] = old_receipt
    receipt_file.write_text(json.dumps(receipts))
    before = graph._head(registry, source)[1]
    with pytest.raises(ValueError, match='replay refused'):
        graph.flush(root, registry)
    assert graph._head(registry, source)[1] == before
    # An actual newer launch still supersedes the stop on a backwards clock.
    service.launch('worker', now=80)
    graph.flush(root, registry)
    latest = graph._head(registry, source)[1]
    entry = next(e for e in latest['agents'] if e['agent'] == 'worker')
    assert latest['complete'] and entry['state'] == 'live' and entry['revision'] > 4


def test_equal_agent_revision_cannot_publish_changed_payload(published_pair):
    root, service, registry, _, _ = published_pair
    source = graph.producer(service.root)
    before = graph._head(registry, source)[1]
    with service.locked() as states:
        states['worker']['state'] = 'live'
    state = service.snapshot()['worker']
    iri, payload, _ = graph.fact('worker', state, registry.onto, source)
    receipt_file = service.root / 'graph-receipts.json'
    receipts = json.loads(receipt_file.read_text())
    receipts['worker'] = dict(revision=state['graph_revision'], iri=iri, payload=payload)
    receipt_file.write_text(json.dumps(receipts))
    with pytest.raises(ValueError, match='content replay refused'):
        graph.flush(root, registry)
    assert graph._head(registry, source)[1] == before


def test_known_agent_cannot_disappear_behind_another_agents_max(published_pair):
    root, service, registry, _, _ = published_pair
    source = graph.producer(service.root)
    before = graph._head(registry, source)[1]
    with service.locked() as states:
        del states['worker']
    with pytest.raises(ValueError, match='agent disappeared'):
        graph.flush(root, registry)
    assert graph._head(registry, source)[1] == before


@pytest.mark.parametrize('invalid', [None, [1], [True, 'a' * 64], [1, 'g' * 64]])
def test_malformed_remote_agent_fence_is_not_repaired_by_guessing(published_pair, invalid):
    root, service, registry, _, _ = published_pair
    source = graph.producer(service.root)
    iri, head = graph._head(registry, source)
    head['revision'] += 1
    head['agent_versions']['worker'] = invalid
    registry.rows[iri] = [dict(payload=json.dumps(head))]
    before_sets = len(registry.head_sets)
    with pytest.raises(ValueError, match='version fences malformed'):
        graph.flush(root, registry)
    assert len(registry.head_sets) == before_sets


def test_hundred_normal_agents_fit_the_head_cap_with_persistent_fences(tmp_path, monkeypatch):
    monkeypatch.setattr(graph, '_set_comment', lambda r, i, p: r.set_comment(i, p))
    service, registry = OwnedWork(tmp_path), Registry()
    for number in range(100):
        service.launch('agent' + str(number), now=100)
    graph.flush(tmp_path, registry, limit=100, budget=5)
    head = graph._head(registry, graph.producer(service.root))[1]
    assert head['complete'] and len(head['agents']) == 100
    assert len(json.dumps(head, sort_keys=True, separators=(',', ':')).encode()) <= 65536
