"""Recruiter capability is narrower than administrator authority; no jobs run."""
from copy import deepcopy
import socket
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from shantytown.actor_identity import IdentityError
from shantytown import recruiter


def policy(root):
    return {'version': 1, 'principals': {'recruiter-test': {
        'uid': 10001, 'host': socket.gethostname(), 'root': str(root), 'repos': ['intigraph/widget'], 'jobs': ['review']}}}


def request(**overrides):
    fields = dict(repo='intigraph/widget', pr=42, job='review', item='task-1',
                  head='a' * 40, checkout=None, harness=None, request_id=None)
    fields.update(overrides)
    return SimpleNamespace(**fields)


def test_exact_protected_scope(tmp_path):
    scope = recruiter._scope(policy(tmp_path), principal='recruiter-test', uid=10001, root=tmp_path, host=socket.gethostname())
    scope.check(request(), root=tmp_path, host=socket.gethostname())
    for changes in ({'repo': 'outside/widget'}, {'repo': 'intigraph/other'}, {'job': 'merge'},
                    {'job': 'task'}, {'checkout': '/tmp/other'}, {'harness': 'other'},
                    {'request_id': 'a' * 64}, {'head': 'short'}, {'pr': True}, {'item': '--bad'}):
        with pytest.raises(IdentityError):
            scope.check(request(**changes), root=tmp_path, host=socket.gethostname())
    with pytest.raises(IdentityError):
        scope.check(request(), root=tmp_path / 'different-root', host=socket.gethostname())


def test_environment_cannot_select_principal_or_expand_scope(tmp_path, monkeypatch):
    monkeypatch.setenv('SHANTY_AGENT', 'administrator')
    monkeypatch.setenv('SHANTY_RECRUITER_REPOS', '*')
    for principal, uid in [('administrator', 10001), ('recruiter-test', 1000), ('recruiter-test', 10002)]:
        with pytest.raises(IdentityError):
            recruiter._scope(policy(tmp_path), principal=principal, uid=uid, root=tmp_path, host=socket.gethostname())


def test_malformed_or_overbroad_policy_refuses(tmp_path):
    for key, value in [('uid', True), ('uid', 1000), ('root', 'relative'), ('host', 'other-host'), ('repos', ['*']),
                       ('repos', ['intigraph/..']), ('jobs', ['task']), ('jobs', []), ('repos', [])]:
        data = deepcopy(policy(tmp_path))
        data['principals']['recruiter-test'][key] = value
        with pytest.raises(IdentityError):
            recruiter._scope(data, principal='recruiter-test', uid=10001, root=tmp_path, host=socket.gethostname())


def test_protected_file_is_checked_before_identity_or_payload(tmp_path):
    path = tmp_path / 'recruiters.json'
    path.write_text('not JSON')
    with patch.object(recruiter, 'POLICY_PATH', path), \
         patch.object(recruiter, 'protected', side_effect=IdentityError('unprotected')), \
         patch.object(recruiter, 'authenticated_actor') as actor:
        with pytest.raises(IdentityError, match='unprotected'):
            recruiter.load(root=tmp_path, host=socket.gethostname())
        actor.assert_not_called()


def test_missing_policy_is_not_an_admin_grant(tmp_path):
    with patch.object(recruiter, 'POLICY_PATH', tmp_path / 'absent'):
        assert recruiter.load(root=tmp_path, host=socket.gethostname()) is None


def test_native_binding_rejects_missing_malformed_wrong_head_repo_pr_and_kind():
    req = request()
    record = dict(schema='chaski.github.work-request/v1', kind='review',
                  repo=req.repo, revision=req.head, facts={'pr': req.pr})
    recruiter.check_binding(req, record)
    for bad in (None, {}, {'body': 'task-1'}, dict(record, revision='b' * 40),
                dict(record, repo='intigraph/other'), dict(record, kind='merge'),
                dict(record, facts={'pr': True}), dict(record, facts={'pr': 43}),
                dict(record, facts=[])):
        with pytest.raises(IdentityError):
            recruiter.check_binding(req, bad)


def test_host_mismatch_and_merge_are_always_held(tmp_path):
    data = policy(tmp_path)
    data['principals']['recruiter-test']['jobs'] = ['review', 'merge']
    scope = recruiter._scope(data, principal='recruiter-test', uid=10001,
                             root=tmp_path, host=socket.gethostname())
    with pytest.raises(IdentityError):
        scope.check(request(job='merge'), root=tmp_path, host=socket.gethostname())
    with pytest.raises(IdentityError):
        scope.check(request(), root=tmp_path, host='other-host')
    with patch.object(recruiter.socket, 'gethostname', return_value='other-host'):
        with pytest.raises(IdentityError):
            scope.check(request(), root=tmp_path, host=scope.host)


def admission_fixture():
    req = request()
    info = dict(state='open', draft=False, number=42, node_id='PR_example',
                author_association='MEMBER', head={'sha': req.head, 'repo': {'full_name': req.repo}},
                base={'ref': 'main', 'repo': {'full_name': req.repo}})
    record = dict(schema='chaski.github.work-request/v1', kind='review', repo=req.repo,
                  revision=req.head, facts={'pr': 42})
    runs = {'total_count': 1, 'check_runs': [dict(name='test', head_sha=req.head,
            status='completed', conclusion='success', app={'id': 7})]}
    statuses = {'sha': req.head, 'total_count': 0, 'statuses': []}
    required = {'contexts': ['test'], 'checks': [{'context': 'test', 'app_id': 7}]}
    decision = {'author_agent_unknown': False, 'approvals': [], 'blocking': []}
    calls = []
    def gh(path):
        calls.append(path)
        if '/pulls/' in path:
            return info
        if '/branches/' in path:
            return required
        if '/check-runs?' in path:
            return runs
        return statuses
    return req, info, record, runs, statuses, required, decision, gh, calls


def test_admission_reads_authority_and_rechecks_custody_and_head():
    req, info, record, runs, statuses, required, decision, gh, calls = admission_fixture()
    bindings = []
    recruiter.admit(req, gh=gh, verdict=lambda *args: decision,
                     binding=lambda item: bindings.append(item) or record)
    assert len(bindings) == 2
    assert calls[0] == calls[-1] == 'repos/intigraph/widget/pulls/42'
    assert any('/protection/required_status_checks' in call for call in calls)


@pytest.mark.parametrize('mutation', ['outside', 'wronghead', 'partial', 'missingrequired',
                                     'wrongapp', 'pending', 'unknownauthor', 'approval', 'changes'])
def test_admission_negative_controls(mutation):
    req, info, record, runs, statuses, required, decision, gh, calls = admission_fixture()
    if mutation == 'outside': info['author_association'] = 'CONTRIBUTOR'
    if mutation == 'wronghead': info['head']['sha'] = 'b' * 40
    if mutation == 'partial': runs['total_count'] = 101
    if mutation == 'missingrequired': required['contexts'].append('absent')
    if mutation == 'wrongapp': required['checks'][0]['app_id'] = 8
    if mutation == 'pending': runs['check_runs'][0]['status'] = 'in_progress'
    if mutation == 'unknownauthor': decision['author_agent_unknown'] = True
    if mutation == 'approval': decision['approvals'].append({'by': 'reviewer'})
    if mutation == 'changes': decision['blocking'].append({'by': 'reviewer'})
    with pytest.raises(IdentityError):
        recruiter.admit(req, gh=gh, verdict=lambda *args: decision, binding=lambda item: record)


def test_changed_head_or_custody_after_checks_refuses():
    for change in ('head', 'binding'):
        req, info, record, runs, statuses, required, decision, gh, calls = admission_fixture()
        def verdict(*args):
            if change == 'head': info['head']['sha'] = 'b' * 40
            else: record['revision'] = 'b' * 40
            return decision
        with pytest.raises(IdentityError):
            recruiter.admit(req, gh=gh, verdict=verdict, binding=lambda item: record)


def test_scoped_authority_does_not_grant_admin_role_or_other_verbs(tmp_path):
    from shantytown import ephemeral
    scope = recruiter._scope(policy(tmp_path), principal='recruiter-test', uid=10001,
                             root=tmp_path, host=socket.gethostname())
    with patch.object(ephemeral.os, 'geteuid', return_value=10001):
        ephemeral.authority('recruiter-test', lambda _: 'worker', require_verified=True,
                            recruiter_scope=scope, request=request(), root=tmp_path,
                            host=socket.gethostname())
        with pytest.raises(ephemeral.Refused):
            ephemeral.authority('recruiter-test', lambda _: 'worker', require_verified=True)
        with pytest.raises(ephemeral.Refused):
            ephemeral.authority('recruiter-test', lambda _: 'worker', require_verified=True,
                                recruiter_scope=scope, request=request(job='merge'), root=tmp_path,
                                host=socket.gethostname())
        with pytest.raises(ephemeral.Refused):
            ephemeral.authority('other', lambda _: 'administrator', require_verified=True,
                                recruiter_scope=scope, request=request(), root=tmp_path,
                                host=socket.gethostname())
