"""Observed lifecycle facts for the held-work reader, separate from identity.

Opt-in publication from existing lifecycle/tend hooks; no listener or polling
agent. A launch fact clears earlier explicit stops, even on a backwards clock.
These are observations of lifecycle intent, NOT native expiry or proof that a
process remains alive. Heartbeats renew observations at most once per five
minutes; an explicit stop cannot be renewed or cleared by a delayed heartbeat.
"""
from __future__ import annotations

from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request

from .files import write_json_atomic
from .owned_work import OwnedWork, _agent, _time, LEASE

RDFS = 'http://www.w3.org/2000/01/rdf-schema#'
SCHEMA = 'https://schema.org/'
CONTRACT = 'shantytown-owned-work/v1'
HEAD_CONTRACT = 'shantytown-owned-work-head/v1'


def producer(root):
    # This head belongs to ONE host and crew root. graph.lock is host-local;
    # another host has a different producer/head and must not be merged into
    # this reader scope merely because it names the same agent.
    identity = socket.gethostname() + '\0' + str(root.resolve())
    return 'urn:shantytown:owned-work:' + hashlib.sha256(identity.encode()).hexdigest()


def fact(agent, state, onto, source):
    agent = _agent(agent)
    if len(agent) > 64:
        raise ValueError('lifecycle agent name exceeds reader bound')
    revision = state.get('graph_revision', 0)
    if type(revision) is not int or not 0 <= revision <= 9007199254740991:
        raise ValueError('invalid lifecycle revision')
    status = state['state']
    if status not in {'live', 'stopped', 'ceiling', 'expired'}:
        raise ValueError('invalid lifecycle state')
    observed = _time(state.get('graph_observed_at', state['observed_at']))
    generation = state['generation']
    if not isinstance(generation, str) or not generation or len(generation) > 128:
        raise ValueError('invalid lifecycle generation')
    payload = json.dumps(dict(contract=CONTRACT, agent=agent, state=status,
                              generation=generation, revision=revision,
                              observed_at=observed), sort_keys=True, separators=(',', ':'))
    digest = hashlib.sha256((source + '\0' + payload).encode()).hexdigest()
    iri = onto + 'owned-work-' + digest
    stamp = datetime.fromtimestamp(observed, timezone.utc).isoformat().replace('+00:00', 'Z')
    review = datetime.fromtimestamp(observed + LEASE, timezone.utc).isoformat().replace('+00:00', 'Z')
    lit = json.dumps
    turtle = '\n'.join([
        f'<{iri}> a <{onto}OperationalFact> ;',
        f' <{RDFS}label> {lit("Lifecycle observation " + agent + " " + str(revision))} ;',
        f' <{onto}sourceKind> "observed" ;',
        f' <{onto}source> {lit(source)} ;',
        f' <{onto}ownedBy> <{onto}{agent}> ;',
        f' <{onto}observedAt> {lit(stamp)} ;',
        f' <{onto}reviewAfter> {lit(review)} ;',
        f' <{SCHEMA}version> {revision} ;',
        f' <{RDFS}comment> {lit(payload)} .',
    ]) + '\n'
    return iri, payload, turtle


def _value(value):
    return value.get('value') if isinstance(value, dict) else value


def present(registry, iri, payload, revision):
    rows = registry._query(
        f'SELECT ?payload ?revision WHERE {{ <{iri}> <{RDFS}comment> ?payload ; '
        f'<{SCHEMA}version> ?revision }} LIMIT 3')
    if not rows:
        return False
    if (len(rows) != 1 or _value(rows[0].get('payload')) != payload
            or str(_value(rows[0].get('revision'))) != str(revision)):
        raise ValueError('lifecycle read-back ambiguous or changed')
    return True


def _set_comment(registry, iri, payload):
    from . import quipu_auth
    headers = quipu_auth.write_headers(registry.server)
    headers['X-Quipu-Client'] = registry.client_label or 'shantytown'
    body = dict(entity=iri, predicate=RDFS + 'comment', value={'str': payload},
                source='shantytown-owned-work')
    request = urllib.request.Request(registry.server + '/set',
                                     data=json.dumps(body).encode(), headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=registry.timeout) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise quipu_auth.refuse(registry.server, 'rejected (HTTP 401)') from None
        raise RuntimeError('lifecycle head HTTP refusal') from None
    if (not isinstance(result, dict) or type(result.get('tx_id')) is not int or result['tx_id'] < 0
            or result.get('entity') != iri or result.get('predicate') != RDFS + 'comment'
            or type(result.get('asserted')) is not int or result['asserted'] not in (0, 1)
            or type(result.get('retracted')) is not int or result['retracted'] < 0):
        raise ValueError('lifecycle head receipt unproven')


def _head(registry, source):
    iri = registry.onto + 'owned-work-head-' + hashlib.sha256(source.encode()).hexdigest()
    rows = registry._query(
        f'SELECT ?payload WHERE {{ <{iri}> a <{registry.onto}OperationalFact> ; '
        f'<{registry.onto}source> {json.dumps(source)} ; <{RDFS}comment> ?payload }} LIMIT 3')
    if not rows:
        return iri, None
    if len(rows) != 1:
        raise ValueError('lifecycle head ambiguous')
    value = json.loads(_value(rows[0].get('payload')))
    if (not isinstance(value, dict) or value.get('contract') != HEAD_CONTRACT
            or value.get('source') != source or type(value.get('revision')) is not int
            or value['revision'] < 1 or type(value.get('state_revision')) is not int
            or value['state_revision'] < 0 or type(value.get('complete')) is not bool
            or type(value.get('source_agents')) is not int
            or not 0 <= value['source_agents'] <= 100
            or not isinstance(value.get('agents'), list)
            or len(value['agents']) > value['source_agents']):
        raise ValueError('lifecycle head malformed')
    if value.get('host') != socket.gethostname():
        raise ValueError('lifecycle head belongs to another source host')
    return iri, value


def _advance_head(registry, service, receipts):
    # One bounded current projection. The immutable facts remain history, but
    # the reader never aggregates that history on every poll.
    if not any(r.get('payload') for r in receipts.values()):
        return
    states = service.snapshot()
    if len(states) > 100:
        raise ValueError('lifecycle writer exceeds 100-agent coverage cap')
    source = producer(service.root)
    iri, previous = _head(registry, source)
    head_receipt_file = service.root / 'graph-head.json'
    has_head_receipt = head_receipt_file.exists()
    head_receipt = json.loads(head_receipt_file.read_text()) if has_head_receipt else None
    if has_head_receipt:
        if (not isinstance(head_receipt, dict) or head_receipt.get('iri') != iri
                or type(head_receipt.get('revision')) is not int
                or head_receipt['revision'] < 1
                or not isinstance(head_receipt.get('sha256'), str)
                or len(head_receipt['sha256']) != 64):
            raise ValueError('local lifecycle head receipt malformed')
        if previous is None or previous['revision'] < head_receipt['revision']:
            raise ValueError('previously observed lifecycle head missing or rolled back')
        previous_hash = hashlib.sha256(json.dumps(previous, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if previous['revision'] == head_receipt['revision'] and previous_hash != head_receipt['sha256']:
            raise ValueError('previously observed lifecycle head changed')
    revision = max([0, *(s.get('graph_revision', 0) for s in states.values())])
    if previous and previous.get('state_revision', previous['revision']) > revision:
        raise ValueError('remote lifecycle head is newer; local replay refused')
    agents, complete = [], bool(states)
    for name, state in sorted(states.items()):
        receipt = receipts.get(name, {})
        payload = receipt.get('payload')
        if payload is None or receipt.get('revision') != state.get('graph_revision', 0):
            complete = False
            continue
        expected_iri, expected_payload, _ = fact(name, state, registry.onto, source)
        if receipt.get('iri') != expected_iri or payload != expected_payload:
            raise ValueError('local lifecycle receipt changed')
        agents.append(dict(fact=receipt['iri'], **json.loads(payload)))
    value = dict(contract=HEAD_CONTRACT, source=source, host=socket.gethostname(), state_revision=revision,
                 complete=complete, source_agents=len(states), agents=agents)
    if previous and {k: v for k, v in previous.items() if k != 'revision'} == value:
        payload = json.dumps(previous, sort_keys=True, separators=(',', ':'))
        write_json_atomic(head_receipt_file, dict(iri=iri, revision=previous['revision'],
                                                 sha256=hashlib.sha256(payload.encode()).hexdigest()))
        return
    # graph.lock is held from the remote revision read through /set and its
    # read-back. /set is NOT CAS: this serialized writer is the monotonicity
    # mechanism, including a partially delivered head becoming complete.
    value['revision'] = previous['revision'] + 1 if previous else 1
    payload = json.dumps(value, sort_keys=True, separators=(',', ':'))
    if len(payload.encode()) > 65536:
        raise ValueError('lifecycle head byte cap exceeded')
    if previous is None:
        registry._knot(f'<{iri}> a <{registry.onto}OperationalFact> ; '
                       f'<{RDFS}label> "Lifecycle writer current head" ; '
                       f'<{registry.onto}sourceKind> "observed" ; '
                       f'<{registry.onto}source> {json.dumps(source)} ; '
                       f'<{RDFS}comment> {json.dumps(payload)} .\n')
    else:
        _set_comment(registry, iri, payload)
    if _head(registry, source)[1] != value:
        raise RuntimeError('lifecycle head read-back unproven')
    write_json_atomic(head_receipt_file, dict(iri=iri, revision=value['revision'],
                                             sha256=hashlib.sha256(payload.encode()).hexdigest()))


def flush(root, registry, *, agents=None, limit=4, budget=5):
    """Only exact pending facts; a failed read never authorizes a write.

    Graph lock serializes delivery, not heartbeat/lifecycle state. Before each
    post recheck the local generation/revision; newer state remains pending.
    A lost ACK is reconciled by exact immutable fact read-back on the next hook.
    """
    service = OwnedWork(root)
    service.version_graph_observations(agents=agents)
    service.root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (service.root / 'graph.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return []
        receipt_file = service.root / 'graph-receipts.json'
        receipts = json.loads(receipt_file.read_text()) if receipt_file.exists() else {}
        states = service.snapshot()
        if len(states) > 100:
            raise ValueError('lifecycle writer exceeds 100-agent coverage cap')
        pending = []
        for name, state in states.items():
            if agents is not None and name not in agents:
                continue
            revision = state.get('graph_revision', 0)
            if revision == 0:
                continue  # A concurrent first heartbeat awaits versioning.
            if receipts.get(name, {}).get('revision', -1) < revision:
                pending.append((name, state))
        # Fairness: delivered older revisions first; a failed owner rotates next
        # pass rather than starving all subsequent owners.
        pending.sort(key=lambda pair: (receipts.get(pair[0], {}).get('attempt', 0), pair[0]))
        started, delivered = time.monotonic(), []
        for name, state in pending[:limit]:
            if time.monotonic() - started >= budget:
                break
            old = receipts.get(name, {})
            receipts[name] = {**old, 'attempt': time.time()}
            write_json_atomic(receipt_file, receipts)
            iri, payload, turtle = fact(name, state, registry.onto, producer(service.root))
            revision = state.get('graph_revision', 0)
            if not present(registry, iri, payload, revision):
                current = service.snapshot().get(name, {})
                if (current.get('generation'), current.get('graph_revision', 0)) != (
                        state['generation'], revision):
                    continue
                registry._knot(turtle)
                if not present(registry, iri, payload, revision):
                    raise RuntimeError('lifecycle write not observed')
            receipts[name] = dict(revision=revision, iri=iri, payload=payload, attempt=time.time())
            write_json_atomic(receipt_file, receipts)
            delivered.append(iri)
        _advance_head(registry, service, receipts)
        return delivered


def enabled(root=None):
    override = os.environ.get('SHANTY_OWNED_WORK_PUBLISH')
    if override is not None:
        return override == '1'
    if root is None:
        return False
    from . import config
    cfg, error = config.load_or_default(root)
    if error:
        raise ValueError('lifecycle publication configuration unreadable')
    return cfg.env.get('SHANTY_OWNED_WORK_PUBLISH') == '1'


def publish(root, *, agents=None):
    from .quipu import QuipuRegistry
    try:
        if not enabled(root):
            return
        registry = QuipuRegistry(root=root, timeout=3, client_label='shantytown')
        flush(root, registry, agents=agents)
    except Exception as exc:
        print('  stopped-owner graph: UNKNOWN (' + type(exc).__name__ +
              '); local evidence retained', file=sys.stderr)
