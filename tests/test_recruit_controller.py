"""Existing-controller source integration; every execution surface is forbidden."""
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from shantytown import cli, config, ephemeral, recruit_controller as rc, recruit_request as rr
from shantytown.actor_identity import IdentityError


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    key = Ed25519PrivateKey.generate()
    pin = rr.Binding('fixture-recruiter', 10001, 'fixture-host', ('intigraph/widget',),
                     key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw), str(tmp_path))
    body = dict(schema=rr.SCHEMA, principal=pin.principal, uid=pin.uid, host=pin.host,
                verb='launch', job='review', item='task-1', repo='intigraph/widget', pr=42,
                head='a' * 40, target=None, nonce='b' * 64, issued_at=100, expires_at=160)
    custody = dict(schema='chaski.github.work-request/v1', kind='review',
                   repo=body['repo'], revision=body['head'], facts={'pr': body['pr']})
    monkeypatch.setattr(rc.os, 'geteuid', lambda: 10002)
    monkeypatch.setattr(rc.socket, 'gethostname', lambda: pin.host)
    monkeypatch.setattr(rr, 'load_controller_binding', lambda: pin)
    ledger = rr.Ledger(tmp_path / 'private-fixture.sqlite')
    calls = []
    def native(item):
        assert item == body['item']
        calls.append('custody')
        return custody.copy()
    def admit(request):
        assert request.head == body['head'] and request.job == 'review'
        calls.append('admit')
    kwargs = dict(policy=SimpleNamespace(require_verified_identity=True), actor='fixture-admin',
                  inside=None, role_of=lambda _: 'administrator', root=tmp_path, host=pin.host,
                  ledger=ledger, native_binding=native, admit=admit, clock=lambda: 110)
    def envelope():
        return dict(body=dict(body), signature=key.sign(rr.message(body)).hex())
    yield SimpleNamespace(pin=pin, body=body, custody=custody, key=key, ledger=ledger,
                          calls=calls, kwargs=kwargs, envelope=envelope)
    ledger.close()


def test_controller_consumes_nonce_before_admission_and_never_executes(ctx, monkeypatch):
    from shantytown import job_launch
    def forbidden(*a, **kw):
        pytest.fail('qualification reached privileged execution or lifecycle')
    for name in ('select', 'probe', 'execute', 'stop', 'stop_native'):
        monkeypatch.setattr(job_launch, name, forbidden)
    monkeypatch.setattr(ephemeral, 'write', forbidden)
    receipt = rc.receive(ctx.envelope(), **ctx.kwargs)
    assert receipt['live'] is False and receipt['execution'] == 'refused'
    assert receipt['durable_acceptance'] is False
    assert ctx.calls == ['custody', 'admit', 'custody']
    assert set(receipt) == {'schema', 'request_sha256', 'principal', 'host', 'verb', 'job',
                            'item', 'repo', 'pr', 'head', 'target', 'live', 'execution',
                            'durable_acceptance'}
    assert len(receipt['request_sha256']) == 64
    other = rr.Ledger(ctx.kwargs['root'] / 'private-fixture.sqlite')
    try:
        with pytest.raises(IdentityError, match='replay'):
            rc.receive(ctx.envelope(), **(ctx.kwargs | {'ledger': other}))
    finally:
        other.close()
    assert ctx.calls.count('admit') == 1


@pytest.mark.parametrize('mutation', ['root', 'host', 'same-uid', 'same-principal', 'unverified', 'worker', 'job'])
def test_wrong_controller_refuses_before_signature_or_custody(ctx, monkeypatch, mutation):
    kw = dict(ctx.kwargs)
    if mutation == 'root':
        kw['root'] = kw['root'] / 'other'
    elif mutation == 'host':
        kw['host'] = 'foreign-host'
    elif mutation == 'same-uid':
        monkeypatch.setattr(rc.os, 'geteuid', lambda: ctx.pin.uid)
    elif mutation == 'same-principal':
        kw['actor'] = ctx.pin.principal
    elif mutation == 'unverified':
        kw['policy'] = SimpleNamespace(require_verified_identity=False)
    elif mutation == 'worker':
        kw['role_of'] = lambda _: 'worker'
    else:
        kw['inside'] = 'eph-review-abcdef'
    with pytest.raises((IdentityError, ephemeral.Refused)):
        rc.receive(ctx.envelope(), **kw)
    assert ctx.calls == []
    assert ctx.ledger.db.execute('SELECT count(*) FROM nonces').fetchone()[0] == 0


def test_changed_custody_after_fresh_checks_refuses_terminally(ctx):
    def admit(_):
        ctx.custody['revision'] = 'c' * 40
    with pytest.raises(IdentityError, match='exact PR'):
        rc.receive(ctx.envelope(), **(ctx.kwargs | {'admit': admit}))
    with pytest.raises(IdentityError, match='replay'):
        rc.receive(ctx.envelope(), **ctx.kwargs)


@pytest.mark.parametrize('moments', [(110, 160), (110, 159, 160)])
def test_expiry_during_fresh_reads_never_extends_signed_lease(ctx, moments):
    clock = iter(moments)
    with pytest.raises(IdentityError, match='expired'):
        rc.receive(ctx.envelope(), **(ctx.kwargs | {'clock': lambda: next(clock)}))
    assert ctx.ledger.db.execute('SELECT reason FROM audit ORDER BY rowid DESC LIMIT 1').fetchone() == ('expiry',)


def test_admission_failure_or_lost_reply_does_not_rearm(ctx):
    def fail(_):
        raise OSError('PRIVATE adapter detail')
    with pytest.raises(OSError):
        rc.receive(ctx.envelope(), **(ctx.kwargs | {'admit': fail}))
    assert ctx.ledger.db.execute('SELECT reason FROM audit ORDER BY rowid DESC LIMIT 1').fetchone() == ('admission',)
    with pytest.raises(IdentityError, match='replay'):
        rc.receive(ctx.envelope(), **ctx.kwargs)


def target(ctx):
    ctx.body.update(verb='stop', target='eph-review-abcdef')
    return dict(name=ctx.body['target'], job='review', state=ephemeral.LIVE,
                **{k: ctx.body[k] for k in ('item', 'repo', 'pr', 'head', 'host')},
                recruiter={k: ctx.body[k] for k in ('principal', 'uid', 'host', 'item', 'repo', 'pr', 'head')}
                | {'binding': 'chaski.github.work-request/v1'},
                uid_binding={'uid': 10003, 'sha256': 'd' * 64})


def test_stop_only_own_exact_live_review_without_forge_or_execution(ctx, monkeypatch):
    rec = target(ctx)
    monkeypatch.setattr(ephemeral, 'read', lambda root, name: rec)
    def forbidden(_):
        pytest.fail('stop should not require current green forge checks')
    receipt = rc.receive(ctx.envelope(), **(ctx.kwargs | {'admit': forbidden}))
    assert receipt['verb'] == 'stop' and receipt['execution'] == 'refused'


@pytest.mark.parametrize('changed', ['missing', 'owner', 'head', 'uid', 'controller-uid', 'done', 'merge', 'digest'])
def test_stop_cannot_name_arbitrary_job_or_shared_identity(ctx, monkeypatch, changed):
    rec = target(ctx)
    if changed == 'missing': rec = None
    elif changed == 'owner': rec['recruiter']['principal'] = 'someone-else'
    elif changed == 'head': rec['head'] = 'f' * 40
    elif changed == 'uid': rec['uid_binding']['uid'] = ctx.pin.uid
    elif changed == 'controller-uid': rec['uid_binding']['uid'] = 10002
    elif changed == 'done': rec['state'] = ephemeral.DONE
    elif changed == 'merge': rec['job'] = 'merge'
    else: rec['uid_binding']['sha256'] = 'short'
    monkeypatch.setattr(ephemeral, 'read', lambda root, name: rec)
    with pytest.raises(IdentityError, match='ownership'):
        rc.receive(ctx.envelope(), **ctx.kwargs)


@pytest.mark.parametrize('raw', [b'', b' '*8193, b'{"body":1,"body":2}', b'{"body":{"uid":1,"uid":2}}', b'{}{}', b'\xff'])
def test_frame_refuses_oversize_duplicate_trailing_or_invalid_json(raw):
    with pytest.raises(IdentityError):
        rc.parse(raw)


def test_existing_cli_routes_exact_signed_frame_to_fresh_admission(ctx, monkeypatch, capsys):
    cfg = config.Config(host_name=ctx.pin.host)
    cfg = replace(cfg, ephemeral=replace(cfg.ephemeral, require_verified_identity=True))
    monkeypatch.setattr(cli.config, 'load_or_default', lambda _: (cfg, None))
    monkeypatch.setattr(cli, '_spawn_actor', lambda **_: 'fixture-admin')
    monkeypatch.setattr(cli, '_spawn_inside', lambda *a, **kw: None)
    monkeypatch.setattr(ephemeral, 'authority', lambda *a, **kw: None)
    monkeypatch.setattr(rc, 'read_input', ctx.envelope)
    monkeypatch.setattr(rc.time, 'time', lambda: 110)
    # receive's default clock is deliberately replaced at the boundary, not
    # a test of stale webhook payloads becoming forge authority.
    original = rc.receive
    monkeypatch.setattr(rc, 'receive', lambda *a, **kw: original(*a, **kw, clock=lambda: 110))
    calls = []
    monkeypatch.setattr(rc.recruiter, 'cli_admit', lambda req, **kw: calls.append(req.head))
    monkeypatch.setattr(cli, '_spawn_item_work_request', lambda a, item: ctx.custody)
    args = cli.build_parser().parse_args(['--root', str(ctx.kwargs['root']), 'agent', 'spawn',
                                         '--recruitment-request', '--dry-run', '--json'])
    assert cli._cmd_spawn(args) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt['live'] is False and receipt['durable_acceptance'] is False
    assert calls == [ctx.body['head']]


@pytest.mark.parametrize('extra', [[], ['--dry-run', '--job', 'merge'],
                                   ['--dry-run', '--head', 'a'*40], ['--dry-run', '--recruiter']])
def test_cli_never_activates_and_rejects_mixed_authority_before_stdin(ctx, monkeypatch, extra):
    def forbidden(): pytest.fail('refused CLI reached input')
    monkeypatch.setattr(rc, 'read_input', forbidden)
    args = cli.build_parser().parse_args(['agent', 'spawn', '--recruitment-request', *extra])
    assert rc.cli_qualify(args, policy=ctx.kwargs['policy'], actor='fixture-admin', inside=None,
                          host=ctx.pin.host, role_of=ctx.kwargs['role_of'], gh=None,
                          quipu=None, binding=None) == 1


def test_process_interruption_after_reservation_stays_spent(ctx):
    def interrupted(_):
        raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        rc.receive(ctx.envelope(), **(ctx.kwargs | {'admit': interrupted}))
    other = rr.Ledger(ctx.kwargs['root'] / 'private-fixture.sqlite')
    try:
        with pytest.raises(IdentityError, match='replay'):
            rc.receive(ctx.envelope(), **(ctx.kwargs | {'ledger': other}))
    finally:
        other.close()


@pytest.mark.parametrize('change', [{'job': 'merge'}, {'verb': 'merge'},
                                    {'argv': ['/caller/program']}, {'public_key': 'caller'}])
def test_controller_rejects_signed_merge_or_caller_execution_fields(ctx, change):
    ctx.body.update(change)
    with pytest.raises(IdentityError):
        rc.receive(ctx.envelope(), **ctx.kwargs)
    assert ctx.calls == []


def test_pipe_frame_and_open_pipe_deadline(ctx, monkeypatch):
    import os
    reader, writer = os.pipe()
    try:
        monkeypatch.setattr(rc.sys, 'stdin', SimpleNamespace(buffer=SimpleNamespace(fileno=lambda: reader)))
        os.write(writer, json.dumps(ctx.envelope()).encode())
        os.close(writer)
        writer = None
        assert rc.read_input() == ctx.envelope()
    finally:
        os.close(reader)
        if writer is not None: os.close(writer)
    reader, writer = os.pipe()
    try:
        monkeypatch.setattr(rc.sys, 'stdin', SimpleNamespace(buffer=SimpleNamespace(fileno=lambda: reader)))
        monkeypatch.setattr(rc.select, 'select', lambda *args: ([], [], []))
        with pytest.raises(IdentityError, match='timed out'):
            rc.read_input()
    finally:
        os.close(reader)
        os.close(writer)
