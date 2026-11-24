"""Private attended custody and ordinary native admission; no live forge calls."""
import json
import os
import sys
from pathlib import Path
from subprocess import CompletedProcess
from types import SimpleNamespace

import pytest

from test_job_review import job  # noqa: F401
from test_review_enqueue import custody  # noqa: F401
from test_attended_review_enqueue import private_policy, signed, forge
from shantytown import config, review_enqueue as custody_module
from shantytown import review_enqueue_attended as adapter

pytestmark = pytest.mark.skipif(not sys.platform.startswith('linux'),
                                reason='Linux directory-FD custody backend')


@pytest.fixture
def prepared(custody, monkeypatch, tmp_path):
    root, _, spec, _, _ = custody
    policy = private_policy(root)
    base = Path(policy.review_enqueue_attended_dir)
    q = signed(monkeypatch, spec['principal'])
    rec = dict(name=spec['principal'], job='review', state='live', harness='codex',
               repo='o/n', pr=5, head='a'*40)
    message = dict(verdict='approve', head=rec['head'], signer='st-review.testhost')
    with custody_module.Store(root, directory=base/'intents') as store:
        retained = store.retain_attended(rec, message, policy, quipu=q, gh=lambda _: forge())
        intent = store.begin(retained['id'])
    request = dict(schema='review-enqueue-action/v1', intent=intent['id'],
                   attempt=intent['attempt'], candidate=intent['candidate'])
    monkeypatch.setattr(adapter.config, 'load_or_default', lambda _: (
        SimpleNamespace(ephemeral=policy), None))
    repositories = base/'bindings/repositories.json'
    repositories.write_text(json.dumps(dict(version=1,repositories={'o/n':dict(checkout='/fixture/checkout')})))
    repositories.chmod(0o600)
    native_dir = root/'native';native_dir.mkdir(mode=0o700)
    native = native_dir/'pr-risk.py';native.write_text('# fixture only\n');native.chmod(0o400)
    # Only test-framework ancestors model the protected production ancestry.
    # The actual native leaf/owned parents remain subject to every real check.
    lstat = Path.lstat
    outer = set(tmp_path.parents)
    def ancestry(path):
        meta = lstat(path)
        if path in outer:
            fields = list(meta);fields[0] &= ~0o022
            return os.stat_result(fields)
        return meta
    monkeypatch.setattr(Path, 'lstat', ancestry)
    # The protected rail is not consulted and then bypassed on refusal.
    monkeypatch.setattr(adapter.native_adapter, 'controller_ready',
                        lambda: pytest.fail('protected controller policy consulted'))
    monkeypatch.setattr(adapter.native_adapter.native_source_pin, 'policy',
                        lambda _: pytest.fail('protected source policy consulted'))
    pr = forge()
    record = dict(id='c'*64,author='lex',snapshot=dict(forge='github',repo='o/n',
        number=5,head=rec['head'],base_ref='main',one_way=False,merge_method='squash'))
    calls = [];after_classify = []
    def run(argv, **kwargs):
        calls.append(argv)
        if argv[:2] == ['gh','api']:
            return CompletedProcess(argv,0,json.dumps(pr),'')
        if 'classify' in argv:
            assert kwargs['umask'] == 0o077 and kwargs['timeout'] <= 45
            path = Path(argv[argv.index('--output')+1])
            fd = os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,'w') as stream: json.dump(record,stream)
            for callback in after_classify: callback(path)
            return CompletedProcess(argv,0,'classified','')
        assert 'enqueue' in argv and 'merge' not in argv
        return CompletedProcess(argv,0,'ENQUEUE VERIFIED '+json.dumps(dict(
            record=record['id'],head=record['snapshot']['head'],entry='MQ_attended')),'')
    def execute():
        return adapter.execute(request,root=root,native=native,quipu=q,run=run)
    return SimpleNamespace(root=root,base=base,policy=policy,q=q,request=request,
        repositories=repositories,native=native,pr=pr,record=record,calls=calls,
        after_classify=after_classify,run=run,execute=execute)


def test_private_attended_native_classify_then_enqueue_once(prepared):
    assert prepared.execute()['receipt'] == 'MQ_attended'
    native_calls = [a for a in prepared.calls if a[:2] != ['gh','api']]
    assert ['classify' in a for a in native_calls] == [True,False]
    assert native_calls[-1][-2:] == ['--diff-bound','--execute']
    assert '--expect-record' in native_calls[-1]
    assert all('-I' in a and '-B' in a for a in native_calls)
    count = len(prepared.calls)
    with pytest.raises((adapter.IdentityError,FileExistsError)):
        prepared.execute()
    assert len(prepared.calls) == count


@pytest.mark.parametrize('fault',['uid','state-mode','mutable-parent','unconfigured',
    'unconsumed','protected','attempt','unenrolled','native-mode','native-symlink'])
def test_unadmitted_controller_state_or_request_cannot_call_native(prepared,fault):
    p = prepared
    if fault == 'uid': p.policy.review_enqueue_attended_uid += 1
    elif fault == 'state-mode': (p.base/'intents').chmod(0o755)
    elif fault == 'mutable-parent': p.base.chmod(0o775)
    elif fault == 'unconfigured': p.policy.review_enqueue_attended_dir = ''
    elif fault == 'unconsumed':
        with custody_module.Store(p.root,directory=p.base/'intents') as store:
            store.finish(p.request['intent'],p.request['attempt'],'unknown','retain uncertainty')
    elif fault == 'protected': p.request['candidate'].pop('report_path')
    elif fault == 'attempt': p.request['attempt'] = 'f'*64
    elif fault == 'unenrolled': p.repositories.write_text(json.dumps(dict(version=1,repositories={})))
    elif fault == 'native-mode': p.native.chmod(0o664)
    elif fault == 'native-symlink':
        retained=p.native.with_suffix('.retained');p.native.rename(retained);p.native.symlink_to(retained)
    with pytest.raises((adapter.IdentityError,OSError)):
        p.execute()
    assert p.calls == []


@pytest.mark.parametrize('fault',['head','author','one-way','mode','late-head','revoked'])
def test_classification_or_late_truth_changes_prevent_enqueue(prepared,monkeypatch,fault):
    p = prepared
    def change(path):
        if fault == 'mode': path.chmod(0o644)
        elif fault == 'late-head': p.pr['head']['sha'] = 'd'*40
        elif fault == 'revoked':
            monkeypatch.setattr(adapter.native_adapter.gate_verdict,'trusted_signers',lambda:{})
        else:
            value=json.loads(path.read_text())
            if fault=='head':value['snapshot']['head']='d'*40
            elif fault=='one-way':value['snapshot']['one_way']=True
            else:value['author']='another'
            path.write_text(json.dumps(value))
    p.after_classify.append(change)
    with pytest.raises((adapter.IdentityError,OSError)):
        p.execute()
    assert any('classify' in a for a in p.calls)
    assert not any('enqueue' in a for a in p.calls)
    assert len(list((p.base/'bindings').glob('*.prepare.json'))) == 1


@pytest.mark.parametrize('fault',['ci-red','hold','lost-reply','wrong-receipt'])
def test_native_gate_failure_or_lost_reply_never_rearms(prepared,fault):
    p=prepared
    def run(argv,**kwargs):
        if 'enqueue' not in argv:return p.run(argv,**kwargs)
        p.calls.append(argv)
        if fault=='lost-reply':raise TimeoutError('possibly committed')
        if fault=='wrong-receipt':return CompletedProcess(argv,0,'ENQUEUE VERIFIED {}','')
        return CompletedProcess(argv,1,'',fault)
    with pytest.raises(adapter.IdentityError,match='UNKNOWN|binding') if fault!='lost-reply' else pytest.raises(TimeoutError):
        adapter.execute(p.request,root=p.root,native=p.native,quipu=p.q,run=run)
    count=len(p.calls)
    with pytest.raises((adapter.IdentityError,FileExistsError)):p.execute()
    assert len(p.calls)==count


@pytest.mark.parametrize('setting',['review_enqueue_attended_uid = true',
    'review_enqueue_attended_uid = -1','review_enqueue_attended_dir = "relative"',
    'review_enqueue_attended_dir = "/private/../other"'])
def test_attended_settings_refuse_ambiguous_identity(tmp_path,setting):
    (tmp_path/config.CONFIG_NAME).write_text('[ephemeral]\n'+setting+'\n')
    with pytest.raises(config.ConfigError):config.load(tmp_path)
