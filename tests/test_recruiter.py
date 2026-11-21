"""Recruiter capability is narrower than administrator authority; no jobs run."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from shantytown.actor_identity import IdentityError
from shantytown import recruiter


def policy(root):
    return {'version': 1, 'principals': {'recruiter-test': {
        'uid': 14000, 'root': str(root), 'repos': ['intigraph/widget'], 'jobs': ['review']}}}


def request(**overrides):
    fields = dict(repo='intigraph/widget', pr=42, job='review', item='task-1',
                  head='a' * 40, checkout=None, harness=None, request_id=None)
    fields.update(overrides)
    return SimpleNamespace(**fields)


def test_exact_protected_scope(tmp_path):
    scope = recruiter._scope(policy(tmp_path), principal='recruiter-test', uid=14000, root=tmp_path)
    scope.check(request(), root=tmp_path)
    for changes in ({'repo': 'outside/widget'}, {'repo': 'intigraph/other'}, {'job': 'merge'},
                    {'job': 'task'}, {'checkout': '/tmp/other'}, {'harness': 'other'},
                    {'request_id': 'a' * 64}, {'head': 'short'}, {'pr': True}, {'item': '--bad'}):
        with pytest.raises(IdentityError):
            scope.check(request(**changes), root=tmp_path)
    with pytest.raises(IdentityError):
        scope.check(request(), root=tmp_path / 'different-root')


def test_environment_cannot_select_principal_or_expand_scope(tmp_path, monkeypatch):
    monkeypatch.setenv('SHANTY_AGENT', 'administrator')
    monkeypatch.setenv('SHANTY_RECRUITER_REPOS', '*')
    for principal, uid in [('administrator', 14000), ('recruiter-test', 1000), ('recruiter-test', 14001)]:
        with pytest.raises(IdentityError):
            recruiter._scope(policy(tmp_path), principal=principal, uid=uid, root=tmp_path)


def test_malformed_or_overbroad_policy_refuses(tmp_path):
    for key, value in [('uid', True), ('uid', 1000), ('root', 'relative'), ('repos', ['*']),
                       ('repos', ['intigraph/..']), ('jobs', ['task']), ('jobs', []), ('repos', [])]:
        data = deepcopy(policy(tmp_path))
        data['principals']['recruiter-test'][key] = value
        with pytest.raises(IdentityError):
            recruiter._scope(data, principal='recruiter-test', uid=14000, root=tmp_path)


def test_protected_file_is_checked_before_identity_or_payload(tmp_path):
    path = tmp_path / 'recruiters.json'
    path.write_text('not JSON')
    with patch.object(recruiter, 'POLICY_PATH', path), \
         patch.object(recruiter, 'protected', side_effect=IdentityError('unprotected')), \
         patch.object(recruiter, 'authenticated_actor') as actor:
        with pytest.raises(IdentityError, match='unprotected'):
            recruiter.load(root=tmp_path)
        actor.assert_not_called()


def test_missing_policy_is_not_an_admin_grant(tmp_path):
    with patch.object(recruiter, 'POLICY_PATH', tmp_path / 'absent'):
        assert recruiter.load(root=tmp_path) is None
