"""Automatic native preparation; private state and synthetic process effects."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from subprocess import CompletedProcess
from types import SimpleNamespace

import pytest

from test_job_review import job  # noqa: F401
from test_review_enqueue import custody  # noqa: F401
from test_review_enqueue_native import case, REAL_APPROVAL  # noqa: F401
from shantytown import config, job_review, review_enqueue_bindings as producer
from shantytown.actor_identity import IdentityError


@pytest.fixture
def prepared(case):
    directory = case.root / 'bindings'
    for path in directory.iterdir(): path.unlink()
    repositories = directory / 'repositories.json'
    repositories.write_text(json.dumps(dict(version=1, repositories={
        case.candidate['repo']: dict(checkout='/fixture/checkout')})))
    repositories.chmod(0o600)
    calls=[]
    after_classify=[]
    def run(argv, **kw):
        calls.append(argv)
        if argv[:2] == ['gh','api']:
            return CompletedProcess(argv,0,json.dumps(case.pr),'')
        if argv[3]=='classify':
            assert kw['umask']==0o077 and kw['timeout']<=45
            path=Path(argv[argv.index('--output')+1])
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w') as stream:json.dump(case.record,stream)
            for callback in after_classify:callback(path)
            return CompletedProcess(argv,0,json.dumps({'id':case.record['id']}),'')
        assert argv[3]=='enqueue'
        return CompletedProcess(argv,0,'ENQUEUE VERIFIED '+json.dumps(dict(
            record=case.record['id'],head=case.candidate['head'],entry='MQ_fixture')),'')
    def execute():
        return producer.execute(case.request,root=case.root,bindings=directory,
                                native=Path('/fixture/pr-risk.py'),quipu=case.q,run=run)
    return SimpleNamespace(case=case,directory=directory,repositories=repositories,
        calls=calls,after_classify=after_classify,run=run,execute=execute)


def kinds(prepared):
    return [a[3] for a in prepared.calls if a[:2]!=['gh','api']]


def test_automatic_classification_and_native_enqueue_each_happen_once(prepared):
    assert prepared.execute()['state']=='queued'
    assert kinds(prepared)==['classify','enqueue']
    argv=next(a for a in prepared.calls if 'classify' in a)
    assert argv[argv.index('--author')+1]=='author'
    assert argv[argv.index('--checkout')+1]=='/fixture/checkout'
    assert len(prepared.calls)==4  # Fresh PR reads before and after classification.
    with pytest.raises((IdentityError,FileExistsError)):prepared.execute()
    assert kinds(prepared)==['classify','enqueue']
    assert len(list(prepared.directory.glob('*.prepare.json')))==1


@pytest.mark.parametrize('fault',['unenrolled','relative','extra','version','readable','symlink','off','source'])
def test_unenrolled_or_unprotected_configuration_does_not_spend_or_enqueue(prepared,monkeypatch,fault):
    p=prepared.repositories
    value=json.loads(p.read_text())
    if fault=='unenrolled':value['repositories']={'other/project':dict(checkout='/fixture/checkout')}
    elif fault=='relative':value['repositories'][prepared.case.candidate['repo']]['checkout']='relative'
    elif fault=='extra':value['unknown']=1
    elif fault=='version':value['version']=True
    if fault in ('unenrolled','relative','extra','version'):p.write_text(json.dumps(value))
    elif fault=='readable':p.chmod(0o644)
    elif fault=='symlink':
        target=p.with_suffix('.retained');p.rename(target);p.symlink_to(target)
    elif fault=='off':
        monkeypatch.setattr(producer.adapter.config,'load_or_default',lambda _: (
            SimpleNamespace(ephemeral=config.Ephemeral()),None))
    elif fault=='source':
        def refuse(_):raise IdentityError('unprotected source')
        monkeypatch.setattr(producer.adapter,'_operator_file',refuse)
    with pytest.raises((IdentityError,OSError)):prepared.execute()
    assert prepared.calls==[]
    assert not list(prepared.directory.glob('*.prepare.json'))


@pytest.mark.parametrize('fault',['head','author','readable','partial','missing','revoked','late-head'])
def test_failed_classification_or_changed_truth_preserves_claim_without_enqueue(prepared,monkeypatch,fault):
    def change(path):
        if fault=='readable':path.chmod(0o644)
        elif fault=='partial':path.write_text('{')
        elif fault=='missing':path.unlink()
        elif fault=='revoked':
            monkeypatch.setattr(producer.adapter.gate_verdict,'trusted_signers',lambda:{})
        elif fault=='late-head':prepared.case.pr['head']['sha']='d'*40
        else:
            value=json.loads(path.read_text())
            if fault=='head':value['snapshot']['head']='d'*40
            else:value['author']='other'
            path.write_text(json.dumps(value))
    prepared.after_classify.append(change)
    with pytest.raises((IdentityError,OSError,ValueError)):prepared.execute()
    assert kinds(prepared)==['classify']
    count=len(prepared.calls)
    with pytest.raises((IdentityError,OSError)):prepared.execute()
    assert len(prepared.calls)==count
    assert len(list(prepared.directory.glob('*.prepare.json')))==1


@pytest.mark.parametrize('phase',['classify','enqueue'])
def test_lost_process_reply_never_repeats_budget_or_mutation(prepared,phase):
    base=prepared.run
    def lost(argv,**kw):
        value=base(argv,**kw)
        if len(argv)>3 and argv[3]==phase:raise TimeoutError('effect may have happened')
        return value
    with pytest.raises(TimeoutError):
        producer.execute(prepared.case.request,root=prepared.case.root,bindings=prepared.directory,
                         native=Path('/fixture/pr-risk.py'),quipu=prepared.case.q,run=lost)
    expected=['classify'] if phase=='classify' else ['classify','enqueue']
    assert kinds(prepared)==expected
    with pytest.raises((IdentityError,OSError)):prepared.execute()
    assert kinds(prepared)==expected


def test_parallel_delivery_has_one_exclusive_preparation(prepared):
    def invoke(_):
        try:return prepared.execute()['state']
        except (IdentityError,OSError):return 'refused'
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(invoke,range(2)))
    assert sorted(results)==['queued','refused']
    assert kinds(prepared)==['classify','enqueue']


def test_classification_budget_leaves_time_for_outer_unknown_receipt(prepared,monkeypatch):
    clock=[0]
    monkeypatch.setattr(producer.time,'monotonic',lambda:clock[0])
    prepared.after_classify.append(lambda _:clock.__setitem__(0,101))
    with pytest.raises(TimeoutError):prepared.execute()
    assert kinds(prepared)==['classify']


@pytest.mark.parametrize('revoked',[False,True])
def test_real_scoped_approval_is_checked_again_after_native_preparation(prepared,monkeypatch,revoked):
    _,pin=job_review.policy(prepared.case.spec)
    monkeypatch.setattr(producer.adapter.gate_verdict,'trusted_signers',lambda:{prepared.case.candidate['signer']:pin})
    monkeypatch.setattr(producer.adapter.gate_verdict,'approval',REAL_APPROVAL)
    prepared.case.record['author']=prepared.case.spec['review']['author_agent']
    if revoked:
        prepared.after_classify.append(lambda _:prepared.case.q.registry.clear())
        with pytest.raises(IdentityError,match='signed APPROVE'):prepared.execute()
        assert kinds(prepared)==['classify']
        print('Revoked after preparation: REFUSED; process calls:', kinds(prepared))
    else:
        assert prepared.execute()['state']=='queued'
        assert kinds(prepared)==['classify','enqueue']
        print('Verified signed APPROVE: queued; process calls:', kinds(prepared))


@pytest.mark.parametrize('fault',['nonzero','no-output','late-off'])
def test_failed_native_classification_never_writes_a_binding_or_enqueues(prepared,monkeypatch,fault):
    base=prepared.run
    def run(argv,**kw):
        value=base(argv,**kw)
        if len(argv)>3 and argv[3]=='classify':
            if fault=='nonzero':return CompletedProcess(argv,1,'','private diagnostic')
            if fault=='no-output':Path(argv[argv.index('--output')+1]).unlink()
            if fault=='late-off':
                monkeypatch.setattr(producer.adapter.config,'load_or_default',lambda _: (
                    SimpleNamespace(ephemeral=config.Ephemeral()),None))
        return value
    with pytest.raises((IdentityError,OSError)):
        producer.execute(prepared.case.request,root=prepared.case.root,bindings=prepared.directory,
                         native=Path('/fixture/pr-risk.py'),quipu=prepared.case.q,run=run)
    assert kinds(prepared)==['classify']
    if fault!='late-off':assert not list(prepared.directory.glob('*.binding.json'))


@pytest.mark.parametrize('payload',['{}','{','{"schema":1,"schema":2}','x'*16385])
def test_binding_process_rejects_malformed_input_without_writes(tmp_path,payload):
    import subprocess
    import sys
    result=subprocess.run([sys.executable,'-m','shantytown.review_enqueue_bindings',
        '--root',str(tmp_path),'--bindings',str(tmp_path/'absent'),
        '--native',str(tmp_path/'never-executed')],input=payload,capture_output=True,text=True,timeout=15)
    assert result.returncode==1 and result.stdout==''
    assert result.stderr.startswith('automatic binding Action unproved: ')
    assert str(tmp_path) not in result.stderr
    assert not list(tmp_path.iterdir())
