"""Requester entrypoint; fake transport, real custody/parser/signature controls."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, PrivateFormat, NoEncryption

from shantytown import recruit_adapter as adapter, recruiter, recruit_request as rr
from shantytown.actor_identity import IdentityError
from test_recruit_handoff import ctx, private_store  # noqa:F401


@pytest.fixture
def entry(ctx, monkeypatch):
    c=ctx
    c.pin=replace(c.pin,principal='crew-recruiter',uid=10001)
    c.body.update(principal=c.pin.principal,uid=10001)
    monkeypatch.setattr(rr,'load_controller_binding',lambda:c.pin)
    scope=recruiter.Scope(c.pin.principal,10001,c.pin.root,c.pin.host,c.pin.repos,('review',))
    monkeypatch.setattr(recruiter,'load',lambda **_:scope)
    monkeypatch.setattr(adapter,'_caller_uid',lambda:10001)
    calls=[]
    class Tracker:
        def get(self,item):
            calls.append(('native-item',item))
            return SimpleNamespace(id=item,description=json.dumps(c.custody))
    def admit(req,**kw):
        recruiter.check_binding(req,kw['binding'](req.item))
        calls.append(('admit',req.head))
    monkeypatch.setattr(recruiter,'cli_admit',admit)
    policy=replace(c.kwargs['policy'],recruitment_launch_ready=True)
    value=adapter.ReviewAdapter(root=c.pin.root,host=c.pin.host,policy=policy,
        tracker=Tracker(),items={('intigraph/widget',42):'task-1'},
        candidate=lambda **kw:SimpleNamespace(**kw),gh=None,quipu=None,
        private_key='/not-a-live-key',clock=lambda:110)
    def sign(body,pin,path):
        c.body.clear();c.body.update(body)
        calls.append(('signed',body['nonce']))
        return c.signed()
    monkeypatch.setattr(adapter,'sign_request',sign)
    def exchange(envelope,**kw):
        calls.append(('sent',envelope['body']['nonce']))
        return dict(state='launched',live=True,head=envelope['body']['head'],name='eph-review-abcdef',
                    operation=hashlib.sha256(rr.message(envelope['body'])).hexdigest())
    monkeypatch.setattr(adapter.recruit_endpoint,'exchange',exchange)
    c.entry,c.calls=value,calls
    c.event={'repository':{'full_name':'intigraph/widget'},'pull_request':{'number':42,'head':{'sha':'a'*40}}}
    return c


def test_source_callbacks_resolve_native_custody_and_sign_only_review(entry):
    c=entry;e=c.entry
    candidate=e.resolve_ready('pull_request',c.event)
    e.admit(candidate)
    receipt=json.loads(e.spawn(candidate))
    assert receipt['state']=='launched' and receipt['head']=='a'*40
    assert [x[0] for x in c.calls]==['native-item','admit','native-item','admit','native-item','signed','sent']
    assert c.body['uid']==10001 and c.body['job']=='review' and c.body['verb']=='launch'
    assert c.body['expires_at']-c.body['issued_at']==60


def test_default_off_is_before_policy_remote_key_and_transport(entry,monkeypatch):
    c=entry;e=c.entry;e.policy=replace(e.policy,recruitment_launch_ready=False)
    def forbidden(*a,**k):pytest.fail('OFF adapter read policy or key')
    monkeypatch.setattr(recruiter,'load',forbidden)
    monkeypatch.setattr(adapter,'sign_request',forbidden)
    for invoke in [lambda:e.resolve_ready('pull_request',c.event),
                   lambda:e.admit(SimpleNamespace(**{k:c.body[k] for k in ['repo','pr','head','item','job']})),
                   lambda:e.spawn(SimpleNamespace(**{k:c.body[k] for k in ['repo','pr','head','item','job']}))]:
        with pytest.raises(IdentityError,match='activation is gated'):invoke()
    assert not c.calls


@pytest.mark.parametrize('change',['uid','route','custody','item-id','merge','pin'])
def test_mismatch_never_signs_or_sends(entry,monkeypatch,change):
    c=entry;e=c.entry
    candidate=e.resolve_ready('pull_request',c.event);c.calls.clear()
    if change=='uid':monkeypatch.setattr(adapter,'_caller_uid',lambda:1000)
    elif change=='route':candidate.item='different-task'
    elif change=='custody':c.custody['revision']='f'*40
    elif change=='item-id':e.tracker.get=lambda _:SimpleNamespace(id='wrong',description=json.dumps(c.custody))
    elif change=='merge':candidate.job='merge'
    else:monkeypatch.setattr(rr,'load_controller_binding',lambda:replace(c.pin,principal='foreign'))
    with pytest.raises((IdentityError,ValueError)):e.spawn(candidate)
    assert not any(x[0] in ('signed','sent') for x in c.calls)


@pytest.mark.parametrize('field,value',[('state','prepared'),('live',False),('head','b'*40),
    ('operation','c'*64),('name','eph-merge-abcdef')])
def test_unproved_receipt_is_not_a_spawn_and_never_retried(entry,monkeypatch,field,value):
    c=entry;e=c.entry;candidate=e.resolve_ready('pull_request',c.event)
    original=adapter.recruit_endpoint.exchange;sent=[]
    def bad(*a,**k):
        sent.append(1);return original(*a,**k)|{field:value}
    monkeypatch.setattr(adapter.recruit_endpoint,'exchange',bad)
    with pytest.raises(IdentityError,match='retain attempt'):e.spawn(candidate)
    assert sent==[1]


@pytest.mark.parametrize('payload',[{},[],{'repository':[]},
    {'repository':{'full_name':'intigraph/widget'},'pull_request':[]},
    {'repository':{'full_name':'intigraph/widget'},'pull_request':{'head':[]}}])
def test_malformed_wake_never_reads_native_state(entry,payload):
    assert entry.entry.resolve_ready('pull_request',payload) is None
    assert not entry.calls


def test_event_mentions_cannot_create_a_route_and_route_input_is_frozen(entry):
    c=entry;c.event['pull_request']['number']=99
    c.event['pull_request']['body']='task-1'
    assert c.entry.resolve_ready('pull_request',c.event) is None
    assert not c.calls
    with pytest.raises(TypeError):c.entry.items[('intigraph/widget',99)]='task-1'


def test_ambiguous_check_wake_is_ignored_without_authority_reads(entry):
    payload={'repository':{'full_name':'intigraph/widget'},'check_run':{'head_sha':'a'*40,'pull_requests':[{'number':42},{'number':43}]}}
    assert entry.entry.resolve_ready('check_run',payload) is None
    assert not entry.calls


def test_real_private_seed_signature_and_custody_negatives(ctx,tmp_path):
    # A disposable key owned by the real test UID; no installed key or UID claim.
    key=Ed25519PrivateKey.generate()
    pin=replace(ctx.pin,uid=os.getuid(),public_key=key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw))
    home=tmp_path/'key-home';home.mkdir(mode=0o700)
    path=home/'seed.hex';path.write_text(key.private_bytes(Encoding.Raw,PrivateFormat.Raw,NoEncryption()).hex());path.chmod(0o400)
    envelope=adapter.sign_request(ctx.body,pin,path)
    key.public_key().verify(bytes.fromhex(envelope['signature']),rr.message(ctx.body))
    path.chmod(0o600)
    with pytest.raises(IdentityError,match='custody'):adapter.sign_request(ctx.body,pin,path)
    path.chmod(0o400)
    with pytest.raises(IdentityError,match='unproved'):adapter.sign_request(ctx.body,replace(pin,public_key=b'x'*32),path)
    linked=home/'linked';linked.symlink_to(path)
    with pytest.raises(OSError):adapter.sign_request(ctx.body,pin,linked)
    hard=home/'hard';os.link(path,hard)
    with pytest.raises(IdentityError,match='custody'):adapter.sign_request(ctx.body,pin,path)


def test_lost_response_propagates_without_automatic_retry(entry,monkeypatch):
    from shantytown.recruit_transport import DeliveryUnknown
    c=entry;e=c.entry;candidate=e.resolve_ready('pull_request',c.event);sent=[]
    def lost(*a,**k):
        sent.append(1);raise DeliveryUnknown('retain attempt')
    monkeypatch.setattr(adapter.recruit_endpoint,'exchange',lost)
    with pytest.raises(DeliveryUnknown):e.spawn(candidate)
    assert sent==[1]


def test_nonfinite_clock_refuses_before_key_or_transport(entry):
    c=entry;e=c.entry;candidate=e.resolve_ready('pull_request',c.event);c.calls.clear();e.clock=lambda:float('nan')
    with pytest.raises(IdentityError,match='clock'):e.spawn(candidate)
    assert not any(x[0] in ('signed','sent') for x in c.calls)


def test_binding_changed_after_signing_never_sends(entry,monkeypatch):
    c=entry;e=c.entry;candidate=e.resolve_ready('pull_request',c.event);c.calls.clear()
    original=adapter.sign_request
    def changed(*a):
        envelope=original(*a)
        monkeypatch.setattr(rr,'load_controller_binding',lambda:replace(c.pin,public_key=b'z'*32))
        return envelope
    monkeypatch.setattr(adapter,'sign_request',changed)
    with pytest.raises(IdentityError,match='binding changed'):e.spawn(candidate)
    assert not any(x[0]=='sent' for x in c.calls)


def test_existing_fixed_file_tracker_is_a_second_native_exact_id_backend(entry,tmp_path):
    from shantytown.files import FilesTracker
    c=entry;e=c.entry
    tracker=FilesTracker(tmp_path/'items')
    item=tracker.create('fixture review request',description=json.dumps(c.custody))
    other=adapter.ReviewAdapter(root=e.root,host=e.host,policy=e.policy,tracker=tracker,
        items={('intigraph/widget',42):item.id},candidate=e.candidate,gh=e.gh,
        quipu=e.quipu,private_key=e.private_key,clock=e.clock)
    candidate=other.resolve_ready('pull_request',c.event)
    assert candidate.item==item.id
    assert other.native_binding(item.id)==c.custody
