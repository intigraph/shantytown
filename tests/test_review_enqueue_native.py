"""Private controller fixtures; no production native command or forge calls."""
import json
import os
from pathlib import Path
from subprocess import CompletedProcess
from types import SimpleNamespace

import pytest

from test_job_review import job  # noqa: F401
from test_review_enqueue import custody, retain  # noqa: F401
from shantytown import config, review_enqueue, review_enqueue_native as adapter
from shantytown.actor_identity import IdentityError

REAL_APPROVAL = adapter.gate_verdict.approval


@pytest.fixture
def case(custody, monkeypatch):
    root, _, spec, q, _ = custody
    with review_enqueue.Store(root) as store:
        intent = store.begin(retain(store, custody)['id'])
    candidate = intent['candidate']
    request = dict(schema='review-enqueue-action/v1', intent=intent['id'],
                   attempt=intent['attempt'], candidate=candidate)
    bindings = root / 'bindings'; bindings.mkdir(mode=0o700)
    record = dict(id='c'*64, author='author', snapshot=dict(forge='github', repo=candidate['repo'],
        number=candidate['pr'], head=candidate['head'], base_ref='main', one_way=False,
        merge_method='squash'))
    binding = dict(version=1, checkout='/fixture/checkout', record=record['id'])
    def write(value, suffix):
        path = bindings / (intent['id'] + suffix)
        path.write_text(json.dumps(value)); path.chmod(0o600)
    write(binding, '.binding.json'); write(record, '.record.json')
    monkeypatch.setattr(adapter.config, 'load_or_default', lambda _: (
        SimpleNamespace(ephemeral=config.Ephemeral(review_enqueue_enabled=True)), None))
    monkeypatch.setattr(adapter, 'controller_ready', lambda: None)
    monkeypatch.setattr(adapter, '_operator_file', lambda _: os.open('/dev/null', os.O_RDONLY))
    monkeypatch.setattr(adapter.gate_verdict, 'trusted_signers', lambda: {candidate['signer']: 'pinned'})
    verdict = dict(approved=True, author_agent='author', approvals=[dict(
        record=candidate['record'], by=candidate['reviewer'])])
    monkeypatch.setattr(adapter.gate_verdict, 'approval', lambda *a, **kw: verdict)
    pr = dict(node_id=candidate['pr_node'], number=candidate['pr'], head=dict(sha=candidate['head']),
              state='open', base=dict(repo=dict(full_name=candidate['repo'])))
    calls = []
    def run(argv, **kw):
        calls.append(argv)
        if argv[:2] == ['gh', 'api']:
            return CompletedProcess(argv, 0, json.dumps(pr), '')
        return CompletedProcess(argv, 0, 'ENQUEUE VERIFIED ' + json.dumps(dict(
            record=record['id'], head=candidate['head'], entry='MQ_fixture')) + '\n', '')
    def execute():
        return adapter.execute(request, root=root, bindings=bindings, native=Path('/fixture/pr-risk.py'),
                               quipu=q, run=run)
    return SimpleNamespace(root=root, request=request, record=record, binding=binding,
        verdict=verdict, pr=pr, calls=calls, write=write, execute=execute, candidate=candidate, spec=spec, q=q)


def test_exact_current_signed_review_reaches_only_native_enqueue(case):
    result = case.execute()
    assert result == dict(schema='review-enqueue-action/v1', intent=case.request['intent'],
                         attempt=case.request['attempt'], state='queued', receipt='MQ_fixture')
    assert len(case.calls) == 2
    argv = case.calls[-1]
    assert argv[3] == 'enqueue' and argv[-2:] == ['--diff-bound', '--execute']
    assert '--expect-record' in argv and '--review-record' not in argv
    assert 'merge' not in argv  # Never mint a native content review or use a merge verb.


@pytest.mark.parametrize('fault', ['request-attempt', 'record-head', 'record-repo', 'one-way',
    'missing-author', 'self-author', 'boolean-version', 'binding-record', 'binding-mode', 'binding-symlink', 'off', 'controller', 'revoked',
    'changes', 'author', 'review-record', 'reviewer', 'pr-node', 'pr-head', 'pr-closed'])
def test_unproved_identity_or_approval_never_reaches_native_queue(case, monkeypatch, fault):
    if fault == 'request-attempt': case.request['attempt'] = 'd'*64
    elif fault.startswith('record-') and fault in ('record-head', 'record-repo'):
        case.record['snapshot'][fault[7:]] = 'wrong'
        case.write(case.record, '.record.json')
    elif fault == 'one-way':
        case.record['snapshot']['one_way'] = True; case.write(case.record, '.record.json')
    elif fault == 'missing-author':
        case.record.pop('author'); case.write(case.record, '.record.json')
    elif fault == 'self-author':
        case.record['author'] = case.candidate['reviewer']; case.write(case.record, '.record.json')
    elif fault == 'boolean-version':
        case.binding['version'] = True; case.write(case.binding, '.binding.json')
    elif fault == 'binding-record':
        case.binding['record'] = 'd'*64; case.write(case.binding, '.binding.json')
    elif fault in ('binding-mode', 'binding-symlink'):
        path = case.root/'bindings'/(case.request['intent']+'.binding.json')
        if fault == 'binding-mode': path.chmod(0o644)
        else:
            target=path.with_suffix('.retained');path.rename(target);path.symlink_to(target)
    elif fault == 'off':
        monkeypatch.setattr(adapter.config, 'load_or_default', lambda _: (SimpleNamespace(
            ephemeral=config.Ephemeral()), None))
    elif fault == 'controller':
        monkeypatch.setattr(adapter, 'controller_ready', lambda: (_ for _ in ()).throw(IdentityError('absent')))
    elif fault == 'revoked': monkeypatch.setattr(adapter.gate_verdict, 'trusted_signers', lambda: {})
    elif fault == 'changes': case.verdict['approved'] = False
    elif fault == 'author': case.verdict['author_agent'] = 'other'
    elif fault == 'review-record': case.verdict['approvals'][0]['record'] = 'another'
    elif fault == 'reviewer': case.verdict['approvals'][0]['by'] = 'another'
    elif fault == 'pr-node': case.pr['node_id'] = 'another'
    elif fault == 'pr-head': case.pr['head']['sha'] = 'd'*40
    elif fault == 'pr-closed': case.pr['state'] = 'closed'
    with pytest.raises((IdentityError, OSError)): case.execute()
    assert all(argv[:2] == ['gh','api'] for argv in case.calls)


def test_helper_failure_is_unknown_not_a_retryable_refusal(case, monkeypatch):
    calls=[]
    def failed(argv, **kw):
        calls.append(argv)
        if argv[:2] == ['gh','api']: return CompletedProcess(argv,0,json.dumps(case.pr),'')
        return CompletedProcess(argv,1,'possibly enqueued','private detail')
    with pytest.raises(IdentityError,match='UNKNOWN'):
        adapter.execute(case.request, root=case.root, bindings=case.root/'bindings',
                        native=Path('/fixture/pr-risk.py'), quipu=object(), run=failed)
    assert len(calls)==2


@pytest.mark.parametrize('fault', ['record', 'head', 'entry', 'lost-reply'])
def test_post_mutation_reply_is_never_inferred_success(case, fault):
    calls=[]
    def run(argv, **kw):
        calls.append(argv)
        if argv[:2] == ['gh','api']: return CompletedProcess(argv,0,json.dumps(case.pr),'')
        if fault == 'lost-reply': raise TimeoutError('may have enqueued')
        receipt=dict(record=case.record['id'],head=case.candidate['head'],entry='MQ_fixture')
        receipt[fault] = ''
        return CompletedProcess(argv,0,'ENQUEUE VERIFIED '+json.dumps(receipt),'')
    with pytest.raises((IdentityError,TimeoutError)):
        adapter.execute(case.request,root=case.root,bindings=case.root/'bindings',
                        native=Path('/fixture/pr-risk.py'),quipu=object(),run=run)
    assert len(calls)==2


@pytest.mark.parametrize('fault', ['off','host','uid','version','extra'])
def test_canonical_policy_contents_fail_closed(tmp_path,monkeypatch,fault):
    value=dict(version=1,enabled=True,host=adapter.socket.gethostname(),uid=os.geteuid(),state_dir='/private')
    if fault=='off':value['enabled']=False
    elif fault=='host':value['host']='other-host'
    elif fault=='uid':value['uid']+=1
    elif fault=='version':value['version']=True
    else:value['unknown']=True
    p=tmp_path/'policy.json';p.write_text(json.dumps(value))
    monkeypatch.setattr(adapter,'_operator_file',lambda _:os.open(p,os.O_RDONLY))
    with pytest.raises(IdentityError):adapter.controller_ready()


def test_actual_operator_path_reader_accepts_root_binary_and_refuses_writable_ancestry(tmp_path):
    # Real descriptor traversal, no exec. This control is independent of the
    # process fixture's synthetic root-pinned native source.
    native=Path('/usr/bin/true').resolve(strict=True)
    fd=adapter._operator_file(native)
    try:assert os.fstat(fd).st_uid==0
    finally:os.close(fd)
    path=tmp_path/'native.py';path.write_text('not executed')
    with pytest.raises(IdentityError):adapter._operator_file(path)


def test_adapter_rechecks_real_scoped_signature_and_quipu_revocation(case, monkeypatch):
    from shantytown import job_review
    _, pin = job_review.policy(case.spec)
    monkeypatch.setattr(adapter.gate_verdict, 'trusted_signers', lambda: {case.candidate['signer']: pin})
    monkeypatch.setattr(adapter.gate_verdict, 'approval', REAL_APPROVAL)
    case.record['author'] = case.spec['review']['author_agent']
    case.write(case.record, '.record.json')
    result = case.execute()
    assert result['state'] == 'queued'
    print('Actual scoped signature + recorded verification:', result['state'])
    print('Native enqueue process calls:', len(case.calls) - 1)
    assert len(case.calls) == 2
    case.q.registry.clear()
    with pytest.raises(IdentityError, match='signed APPROVE'):
        case.execute()
    assert len(case.calls) == 3  # Only the fresh forge read, no second native execute.
    print('After verifier revocation: REFUSED; native calls remain', len(case.calls) - 2)


@pytest.mark.parametrize('payload', ['{}', '{', '{"schema":1,"schema":2}', 'x' * (review_enqueue.MAX_BYTES+1)])
def test_process_entrypoint_refuses_bad_input_without_binding_or_native_effect(tmp_path,payload):
    import subprocess
    import sys
    result=subprocess.run([sys.executable,'-m','shantytown.review_enqueue_native',
        '--root',str(tmp_path),'--bindings',str(tmp_path/'absent'),
        '--native',str(tmp_path/'never-executed')],input=payload,capture_output=True,text=True,timeout=15)
    assert result.returncode==1 and result.stdout==''
    assert result.stderr.startswith('native Action unproved: ')
    assert str(tmp_path) not in result.stderr
    assert not list(tmp_path.iterdir())
