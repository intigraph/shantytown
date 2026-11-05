"""Unprivileged mailbox fixtures; no actual helper, sudo or UID changes."""
import json
import os
from pathlib import Path

import pytest

from shantytown import job_mailbox as box
from shantytown.actor_identity import IdentityError


@pytest.fixture
def mailbox(tmp_path):
    base = tmp_path / 'protected'
    (base / 'messages').mkdir(parents=True, mode=0o700)
    spec = {'principal': 'eph-task-123abc', 'uid': 51001}
    digest = 'a' * 64
    def trust(path, **kw):
        path = Path(path)
        assert path.is_relative_to(base)
        if path.is_symlink() or path.lstat().st_uid != os.geteuid() or path.lstat().st_mode & 0o022:
            raise IdentityError('untrusted fixture')
    def send(value):
        return box.submit(base, spec, digest, value, trust=trust, owner=os.geteuid())
    return base, spec, digest, trust, send


def test_result_submission_is_private_first_wins_and_retries_are_idempotent(mailbox):
    base, spec, digest, trust, send = mailbox
    value = {'kind': 'report', 'verdict': 'done', 'summary': 'own result'}
    first = send(value)
    path = base / 'messages' / (spec['principal'] + '.json')
    assert path.stat().st_mode & 0o777 == 0o600
    assert send(value) == first == box.read(base, spec, digest, trust=trust)
    before = path.read_bytes()
    with pytest.raises(IdentityError, match='no replacement'):
        send(dict(value, verdict='approve'))
    assert path.read_bytes() == before
    assert list(base.iterdir()) == [base / 'messages']  # no controller ledger


def test_turn_tokens_count_once_and_cannot_rewrite_context(mailbox):
    base, spec, digest, trust, send = mailbox
    turn = {'kind': 'turn', 'token': 'b' * 64, 'context_k': 32.0}
    assert len(send(turn)['turns']) == 1
    assert len(send(turn)['turns']) == 1
    with pytest.raises(IdentityError, match='different content'):
        send(dict(turn, context_k=0))
    second = send(dict(turn, token='c' * 64, context_k=64.0))
    assert len(second['turns']) == 2
    assert box.read(base, spec, digest, trust=trust) == second


@pytest.mark.parametrize('value', [
    {}, {'kind': 'stop'}, {'kind': 'report', 'verdict': 'done', 'summary': 'x', 'principal': 'boss'},
    {'kind': 'report', 'verdict': 'admin', 'summary': 'x'},
    {'kind': 'report', 'verdict': 'done', 'summary': 'x' * 1501},
    {'kind': 'turn', 'token': '../other', 'context_k': 0},
    {'kind': 'turn', 'token': 'b' * 64, 'context_k': float('nan')},
    {'kind': 'turn', 'token': 'b' * 64, 'context_k': True},
])
def test_bad_submission_has_no_mailbox_effect(mailbox, value):
    base, _, _, _, send = mailbox
    with pytest.raises(IdentityError):
        send(value)
    assert list((base / 'messages').iterdir()) == []


@pytest.mark.parametrize('fault', ['other-uid', 'other-digest', 'symlink', 'world-readable', 'pending'])
def test_mailbox_binding_private_mode_and_interrupted_write_refuse(mailbox, fault):
    base, spec, digest, trust, send = mailbox
    value = {'kind': 'report', 'verdict': 'done', 'summary': 'own'}
    send(value)
    path = base / 'messages' / (spec['principal'] + '.json')
    if fault == 'other-uid':
        data = json.loads(path.read_text());data['uid'] += 1;path.write_text(json.dumps(data))
    elif fault == 'other-digest':
        data = json.loads(path.read_text());data['sha256'] = 'b' * 64;path.write_text(json.dumps(data))
    elif fault == 'symlink':
        other = path.with_suffix('.retained');path.rename(other);path.symlink_to(other)
    elif fault == 'world-readable':
        path.chmod(0o644)
    else:
        path.with_suffix('.pending').write_text('interrupted; retain')
    before = path.read_bytes()
    with pytest.raises((IdentityError, OSError)):
        send(value)
    assert path.read_bytes() == before


def test_exhausted_mailbox_never_recycles_turn_tokens(mailbox, monkeypatch):
    _, _, _, _, send = mailbox
    monkeypatch.setattr(box, 'MAX_TURNS', 1)
    send({'kind': 'turn', 'token': 'b' * 64, 'context_k': 1})
    with pytest.raises(IdentityError, match='exhausted'):
        send({'kind': 'turn', 'token': 'c' * 64, 'context_k': 2})
