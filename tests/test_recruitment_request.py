"""Offline protocol controls only: never launches a job or installs a key."""

import pytest
from dataclasses import replace
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from shantytown.actor_identity import IdentityError
from shantytown import recruit_request as rr


@pytest.fixture
def context(tmp_path):
    key = Ed25519PrivateKey.generate()
    pin = rr.Binding('test-recruiter', 10001, 'test-host', ('intigraph/widget',),
                     key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))
    body = dict(schema=rr.SCHEMA, principal=pin.principal, uid=pin.uid, host=pin.host,
                verb='launch', job='review', item='task-1', repo='intigraph/widget', pr=42,
                head='a' * 40, target=None, nonce='b' * 64, issued_at=100, expires_at=160)
    ledger = rr.Ledger(tmp_path / 'nonce.sqlite')
    yield key, pin, body, ledger
    ledger.close()


def signed(key, body):
    return {'body': body, 'signature': key.sign(rr.message(body)).hex()}


def native(item):
    assert item == 'task-1'
    return dict(schema='chaski.github.work-request/v1', kind='review',
                repo='intigraph/widget', revision='a' * 40, facts={'pr': 42})


def test_valid_then_replay_even_after_reopen(context, tmp_path):
    key, pin, body, ledger = context
    envelope = signed(key, body)
    assert rr.qualify(envelope, binding=pin, now=110, ledger=ledger, native_binding=native) == body
    other = rr.Ledger(tmp_path / 'nonce.sqlite')
    try:
        with pytest.raises(IdentityError, match='replay'):
            rr.qualify(envelope, binding=pin, now=110, ledger=other, native_binding=native)
    finally:
        other.close()


@pytest.mark.parametrize('changes', [
    {'principal': 'administrator'}, {'uid': True}, {'uid': 10002}, {'host': 'other'},
    {'verb': 'shell'}, {'job': 'merge'}, {'repo': 'intigraph/other'}, {'pr': True},
    {'head': 'short'}, {'item': '--bad'}, {'target': 'eph-review-abcdef'},
    {'expires_at': 110}, {'issued_at': 111}, {'expires_at': 221}, {'nonce': 'short'},
    {'command': 'anything'}, {'public_key': 'attacker'}, {'environment': {}},
])
def test_signed_but_forbidden_refuses_before_custody(context, changes):
    key, pin, body, ledger = context
    body.update(changes)
    def forbidden(_):
        pytest.fail('forbidden request reached custody adapter')
    with pytest.raises(IdentityError):
        envelope = signed(key, body)
        rr.qualify(envelope, binding=pin, now=110, ledger=ledger, native_binding=forbidden)


def test_wrong_signer_and_tampering(context):
    key, pin, body, ledger = context
    wrong = Ed25519PrivateKey.generate()
    with pytest.raises(IdentityError, match='signature'):
        rr.qualify(signed(wrong, body), binding=pin, now=110, ledger=ledger, native_binding=native)
    envelope = signed(key, body)
    envelope['body'] = dict(body, pr=43)
    with pytest.raises(IdentityError, match='signature'):
        rr.qualify(envelope, binding=pin, now=110, ledger=ledger, native_binding=native)


@pytest.mark.parametrize('record', [None, {}, {'body': 'task-1'},
    dict(schema='chaski.github.work-request/v1', kind='review', repo='intigraph/widget',
         revision='c' * 40, facts={'pr': 42})])
def test_native_custody_refusal_is_terminal_and_audited(context, record):
    key, pin, body, ledger = context
    envelope = signed(key, body)
    with pytest.raises(IdentityError):
        rr.qualify(envelope, binding=pin, now=110, ledger=ledger, native_binding=lambda _: record)
    assert ledger.db.execute('SELECT outcome, reason FROM audit').fetchall() == [('refused', 'custody')]
    with pytest.raises(IdentityError, match='replay'):
        rr.qualify(envelope, binding=pin, now=110, ledger=ledger, native_binding=native)


def test_stop_has_fixed_review_target_and_no_execution(context):
    key, pin, body, ledger = context
    body.update(verb='stop', target='eph-review-abcdef')
    assert rr.qualify(signed(key, body), binding=pin, now=110, ledger=ledger,
                      native_binding=native)['target'] == 'eph-review-abcdef'
    # Qualification does not claim target ownership or authorize native stop;
    # the existing controller must recheck its ledger when integrated.


def test_controller_loader_cross_checks_protected_identity(context, monkeypatch, tmp_path):
    _, pin, _, _ = context
    data = dict(version=1, principal=pin.principal, uid=pin.uid, host=pin.host,
                root=str(tmp_path), repos=list(pin.repos), public_key=pin.public_key.hex())
    identity = {'version': 1, 'required': True, 'users': {str(pin.uid): {
        'principal': pin.principal, 'home': '/var/lib/shantytown/agents/crew-' + pin.principal}}}
    monkeypatch.setattr(rr.socket, 'gethostname', lambda: pin.host)
    def read(path):
        return data if path == rr.CONTROLLER_BINDING_PATH else identity
    monkeypatch.setattr(rr, '_protected_json', read)
    assert rr.load_controller_binding() == replace(pin, root=str(tmp_path))
    identity['users'][str(pin.uid)]['principal'] = 'other'
    with pytest.raises(IdentityError, match='unique matching'):
        rr.load_controller_binding()


@pytest.mark.parametrize('changes', [{'host': 'wrong-host'}, {'uid': True},
    {'public_key': 'short'}, {'public_key_path': '/caller/key'}, {'repos': ['*']}])
def test_controller_loader_refuses_bad_scope_before_identity(context, monkeypatch, tmp_path, changes):
    _, pin, _, _ = context
    data = dict(version=1, principal=pin.principal, uid=pin.uid, host=pin.host,
                root=str(tmp_path), repos=list(pin.repos), public_key=pin.public_key.hex())
    data.update(changes)
    monkeypatch.setattr(rr.socket, 'gethostname', lambda: pin.host)
    def read(path):
        assert path == rr.CONTROLLER_BINDING_PATH
        return data
    monkeypatch.setattr(rr, '_protected_json', read)
    with pytest.raises(IdentityError):
        rr.load_controller_binding()


def test_unprotected_controller_binding_refuses_before_open(tmp_path, monkeypatch):
    from shantytown import job_launch
    path = tmp_path / 'binding.json'
    path.write_text('{}')
    def refuse(_):
        raise IdentityError('unprotected fixture')
    monkeypatch.setattr(job_launch, 'protected', refuse)
    with pytest.raises(IdentityError, match='unprotected'):
        rr._protected_json(path)


def test_controller_reader_uses_fixed_root_pin_and_rejects_duplicate_keys(tmp_path, monkeypatch):
    from shantytown import advise_signing, job_launch
    path = tmp_path / 'controller.json'
    checked = []
    monkeypatch.setattr(job_launch, 'protected', lambda p: checked.append(p))
    def read(p, *, owner, maximum):
        assert checked == [path]
        assert p == path and owner == 0 and maximum == 1024 * 1024
        return b'{"version":1,"version":2}'
    monkeypatch.setattr(advise_signing, '_read', read)
    with pytest.raises(IdentityError, match='duplicate'):
        rr._protected_json(path)


def test_controller_reader_does_not_fall_back_on_untrusted_key_file(tmp_path, monkeypatch):
    from shantytown import advise_signing, job_launch
    monkeypatch.setattr(job_launch, 'protected', lambda _: None)
    def read(*args, **kwargs):
        raise ValueError('unqualified file')
    monkeypatch.setattr(advise_signing, '_read', read)
    with pytest.raises(IdentityError, match='refused'):
        rr._protected_json(tmp_path / 'controller.json')
