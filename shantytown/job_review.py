"""One isolated job's pre-enrolled review key; no host-key fallback/enrollment."""
from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import stat
import time

from . import gate_verdict as gv
from .actor_identity import IdentityError


def policy(spec):
    value = spec.get('review')
    if (not isinstance(value, dict)
            or set(value) != {'graph', 'signer', 'key', 'public_key', 'repo', 'pr', 'pr_node', 'head', 'author_agent'}
            or spec['request']['job'] != 'review'
            or value['repo'] != spec['request']['repo'] or value['pr'] != spec['request']['pr']
            or value['key'] != str(Path(spec['home']) / '.local/state/shantytown/verdict-signer.pk8')):
        raise IdentityError('review needs its own explicit protected signing policy')
    pin = {key: value[key] for key in ('public_key', 'repo', 'pr', 'pr_node', 'head', 'author_agent')}
    pin['principal'] = spec['principal']
    if not gv.valid_job_pin(value['signer'], pin):
        raise IdentityError('invalid scoped job signer policy')
    if not isinstance(value['graph'], str):
        raise IdentityError('review graph must be explicit')
    try:
        gv._graph(value['graph'])
    except gv.VerdictError:
        raise IdentityError('review graph is not a safe explicit graph') from None
    return value, pin


def private_read(path, uid, maximum):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        meta = os.fstat(stream.fileno())
        if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != uid or meta.st_mode & 0o077
                or meta.st_size > maximum):
            raise IdentityError('job signing state is not private to its UID')
        return stream.read(maximum + 1)


def connection(spec=None):
    from . import actor_identity
    row = actor_identity._policy(actor_identity.POLICY_PATH)
    if row is None or spec is not None and (row['principal'] != spec['principal'] or row['home'] != spec['home']):
        raise IdentityError('review service has no protected caller identity')
    return gv.Quipu(row['endpoint'])


def enrolled(value, pin):
    if gv.trusted_signers().get(value['signer']) != pin:
        raise IdentityError('job review key/scope is not operator-pinned')


def proof(record, value):
    return {'record': record.iri, 'head': record.head, 'signer': value['signer']}


def confirmed(spec, message, *, quipu=None):
    if gv.outcome_word(message.get('verdict')) is None:
        return False
    value, pin = policy(spec)
    enrolled(value, pin)
    supplied = message.get('review')
    if (not isinstance(supplied, dict) or set(supplied) != {'record', 'head', 'signer'}
            or supplied['head'] != value['head'] or supplied['signer'] != value['signer']):
        return False
    result = gv.approval(quipu or connection(), repo=value['repo'], pr=value['pr'],
                         node_id=value['pr_node'], head=value['head'], graph=value['graph'],
                         signers={value['signer']: pin})
    words = result['approvals'] if gv.outcome_word(message['verdict']) == 'approve' else result['blocking']
    return any(word['by'] == spec['principal'] and word['record'] == supplied['record'] for word in words)


def write(spec, verdict, head, evidence, *, quipu=None, now=None):
    """Prepare once, send once; an uncertain retry only verifies the same record."""
    value, pin = policy(spec)
    if os.geteuid() != spec['uid'] or head != value['head'] or gv.outcome_word(verdict) is None:
        raise IdentityError('review caller/head/outcome differs from its protected slot')
    enrolled(value, pin)
    client = quipu or connection(spec)
    if gv.author_agent(client, value['pr_node'], graph=value['graph']) != value['author_agent'].lower():
        raise IdentityError('review authorship differs from its protected slot')
    # Read only a pre-existing own key. Never generate, enroll or select the
    # controller's default key from config/environment on this path.
    seed = gv._seed_of(private_read(value['key'], spec['uid'], 256))
    if gv.public_key(seed).hex() != value['public_key']:
        raise IdentityError('job review key differs from the protected public key')
    record = gv.GateApproval(repo=value['repo'], pr=value['pr'], pr_node=value['pr_node'],
        head=head, outcome=gv.outcome_word(verdict), by=spec['principal'],
        author_agent=value['author_agent'], evidence=evidence or '',
        recorded_at=gv.now_stamp(time.time() if now is None else now))
    record.check()
    path = Path(spec['home']) / '.local/state/shantytown/review-result.json'
    try:
        old = json.loads(private_read(path, spec['uid'], 8192))
    except FileNotFoundError:
        old = None
    if old is not None:
        if not isinstance(old, dict) or set(old) != set(asdict(record)):
            raise IdentityError('invalid prepared review state')
        prior = gv.GateApproval(**old)
        prior.check()
        if {k: v for k, v in old.items() if k != 'recorded_at'} != {
                k: v for k, v in asdict(record).items() if k != 'recorded_at'}:
            raise IdentityError('job already prepared a different review result')
        message = {'verdict': verdict, 'review': proof(prior, value)}
        if not confirmed(spec, message, quipu=client):
            raise IdentityError('prepared review effect is unproved; no automatic resend')
        return message['review']
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(asdict(record), stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    gv.write(record, quipu=client, graph=value['graph'], seed=seed, verifier=value['signer'])
    message = {'verdict': verdict, 'review': proof(record, value)}
    if not confirmed(spec, message, quipu=client):
        raise IdentityError('written review effect is not independently verified')
    return message['review']
