"""Real durable fixtures and planner, fake forge/capability/governor; no launch."""
from copy import deepcopy
from dataclasses import replace
import os
import sys
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from shantytown.actor_identity import IdentityError
from shantytown import config, ephemeral, recruit_handoff as handoff, recruit_request as rr
from shantytown import recruit_store as rs
from test_recruit_store import private_store  # noqa: F401 — shared explicit outer-ancestry fixture


pytestmark = pytest.mark.skipif(not sys.platform.startswith('linux'), reason='Linux persistent controller backend')


@pytest.fixture
def ctx(private_store, monkeypatch):
    pin, directory = private_store
    key = Ed25519PrivateKey.generate()
    pin = replace(pin, public_key=key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))
    body = dict(schema=rr.SCHEMA, principal=pin.principal, uid=pin.uid, host=pin.host,
                verb='launch', job='review', item='task-1', repo='intigraph/widget', pr=42,
                head='a'*40, target=None, nonce='b'*64, issued_at=100, expires_at=160)
    custody = dict(schema='chaski.github.work-request/v1', kind='review', repo=body['repo'],
                   revision=body['head'], facts={'pr': body['pr']})
    capability = dict(uid=os.geteuid()+10002, principal='eph-review-abcdef')
    selected = (capability, 'd'*64)
    monkeypatch.setattr(rr, 'load_controller_binding', lambda: pin)
    monkeypatch.setattr(handoff.recruit_controller.socket, 'gethostname', lambda: pin.host)
    monkeypatch.setattr(handoff.quiet_time, 'read', lambda _: SimpleNamespace(held=False, state='clear', entries=()))
    monkeypatch.setattr(handoff.window, 'active', lambda _: None)
    calls = []
    def select(req, **kw):
        assert kw['native_probe'] is False
        calls.append('select')
        return deepcopy(selected)
    monkeypatch.setattr(handoff.job_launch, 'select', select)
    def admit(req, **kw):
        assert req.head == 'a'*40
        calls.append('admit')
    monkeypatch.setattr(handoff.recruiter, 'cli_admit', admit)
    policy = replace(config.Config().ephemeral, require_verified_identity=True,
                     unattended=True, unattended_uid_ready=True)
    kwargs = dict(root=pin.root, host=pin.host, policy=policy, actor='fixture-admin',
                  inside=None, role_of=lambda _: 'administrator', administrator='fixture-admin',
                  unattended=True, native_binding=lambda item: deepcopy(custody), gh=None, quipu=None,
                  governor=lambda agent: '', clock=lambda: 110)
    def signed():
        return dict(body=deepcopy(body), signature=key.sign(rr.message(body)).hex())
    return SimpleNamespace(pin=pin, directory=directory, body=body, custody=custody,
                           selected=selected, calls=calls, kwargs=kwargs, signed=signed)


def test_durable_handoff_runs_existing_planner_but_never_executes(ctx, monkeypatch):
    def forbidden(*a, **kw): pytest.fail('source handoff attempted execution/lifecycle')
    for name in ('probe', 'execute', 'stop', 'stop_native', 'command'):
        monkeypatch.setattr(handoff.job_launch, name, forbidden)
    monkeypatch.setattr(ephemeral, 'write', forbidden)
    receipt = handoff.prepare(ctx.signed(), **ctx.kwargs)
    assert ctx.calls == ['admit', 'select', 'select']
    assert receipt['nonce_durable'] is True and receipt['execution'] == 'refused'
    assert receipt['live'] is False and receipt['activation'] == 'gated'
    assert receipt['state'] == 'prepared' and receipt['name'] == 'eph-review-abcdef'
    assert len(receipt['plan_sha256']) == 64
    assert not list((ctx.directory.parent).glob('eph-*.json'))
    with rs.Store(ctx.pin) as store:
        assert store.db.execute('SELECT state,plan_digest FROM operations').fetchall() == [('prepared', receipt['plan_sha256'])]
    with pytest.raises(IdentityError, match='replay'):
        handoff.prepare(ctx.signed(), **ctx.kwargs)
    ctx.body['nonce'] = 'c'*64
    with pytest.raises(IdentityError, match='already claimed'):
        handoff.prepare(ctx.signed(), **ctx.kwargs)
    assert ctx.calls.count('select') == 2


@pytest.mark.parametrize('gate', ['cap', 'quiet', 'quiet-unknown', 'maintenance', 'governor',
                                  'governor-unknown', 'unattended', 'uid-ready', 'same-recruiter',
                                  'same-controller', 'capability-changed', 'custody-changed', 'expiry'])
def test_launch_gates_refuse_and_keep_attempt_terminal(ctx, monkeypatch, gate):
    kw = dict(ctx.kwargs)
    if gate == 'cap': kw['policy'] = replace(kw['policy'], max_agents=0)
    elif gate == 'quiet':
        monkeypatch.setattr(handoff.quiet_time, 'read', lambda _: SimpleNamespace(held=True, state='active', entries=()))
    elif gate == 'quiet-unknown':
        monkeypatch.setattr(handoff.quiet_time, 'read', lambda _: SimpleNamespace(held=False, state='unknown', entries=()))
    elif gate == 'maintenance': monkeypatch.setattr(handoff.window, 'active', lambda _: {'state':'active'})
    elif gate == 'governor': kw['governor'] = lambda _: 'capacity exceeded'
    elif gate == 'governor-unknown': kw['governor'] = lambda _: None
    elif gate == 'unattended': kw['unattended'] = False
    elif gate == 'uid-ready': kw['policy'] = replace(kw['policy'], unattended_uid_ready=False)
    elif gate == 'same-recruiter': ctx.selected[0]['uid'] = ctx.pin.uid
    elif gate == 'same-controller': ctx.selected[0]['uid'] = os.geteuid()
    elif gate == 'capability-changed':
        def change(_):
            ctx.selected[0]['uid'] += 1
            return ''
        kw['governor'] = change
    elif gate == 'custody-changed':
        def change(_):
            ctx.custody['revision'] = 'f'*40
            return ''
        kw['governor'] = change
    else:
        # Share clock state across the real admission calls.
        now = [110]
        kw['clock'] = lambda: now[0]
        kw['governor'] = lambda _: now.__setitem__(0, 160) or ''
    with pytest.raises((IdentityError, ephemeral.Refused)):
        handoff.prepare(ctx.signed(), **kw)
    with rs.Store(ctx.pin) as store:
        assert store.db.execute('SELECT state FROM operations').fetchall() == [('refused',)]
        assert store.db.execute('SELECT count(*) FROM nonces').fetchone() == (1,)
    with pytest.raises(IdentityError, match='replay'):
        handoff.prepare(ctx.signed(), **ctx.kwargs)


def test_process_interruption_after_claim_is_never_rearmed(ctx):
    def interrupted(_): raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        handoff.prepare(ctx.signed(), **(ctx.kwargs | {'governor': interrupted}))
    with rs.Store(ctx.pin) as store:
        assert store.db.execute('SELECT state FROM operations').fetchall() == [('refused',)]
    with pytest.raises(IdentityError, match='replay'):
        handoff.prepare(ctx.signed(), **ctx.kwargs)


def test_missing_store_fails_before_forge_or_fresh_admission(ctx):
    ctx.directory.rmdir()
    with pytest.raises(OSError): handoff.prepare(ctx.signed(), **ctx.kwargs)
    assert ctx.calls == []


def test_incomplete_controller_job_inventory_is_unknown_not_free_capacity(ctx):
    path = ctx.directory.parent / 'eph-review-123456.json'
    path.write_text('corrupt ledger fixture')
    with pytest.raises(IdentityError, match='inventory incomplete'):
        handoff.prepare(ctx.signed(), **ctx.kwargs)
    assert path.read_text() == 'corrupt ledger fixture'


def test_wrong_controller_host_refuses_before_creating_store(ctx):
    with pytest.raises(IdentityError, match='protected binding'):
        handoff.prepare(ctx.signed(), **(ctx.kwargs | {'host': 'other-host'}))
    assert not (ctx.directory / rs.NAME).exists()
