import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from shantytown import agy_job


def stream(model='gemini-test',response=None,**result):
    data={'status':'SUCCESS','response':response or json.dumps({'verdict':'APPROVE','summary':'No defects in supplied diff','findings':[]})}
    data.update(result)
    return '\n'.join(json.dumps(x) for x in [{'event':'init','init':{'model':model}},{'event':'result','result':data}])


def test_verdict_requires_exact_model_complete_response_and_schema():
    assert agy_job.parse_result(stream(),'gemini-test')[0]['verdict']=='APPROVE'
    for value in [stream(model='fallback'),stream(response=' '),stream(finished_reason='print_timeout'),
                  stream(response='{"verdict":"APPROVE","summary":"x"}'),
                  stream(response='{"verdict":"APPROVE","summary":"x","findings":[{}]}')]:
        with pytest.raises(ValueError):agy_job.parse_result(value,'gemini-test')
    with pytest.raises(ValueError):agy_job.parse_result(stream()+'\n'+json.dumps({'event':'step_update','step_update':{'step_type':'tool'}}),'gemini-test')


def test_real_auth_copy_is_private_removed_on_exception(tmp_path):
    auth=tmp_path/'auth';auth.write_text('fixture-not-a-token');auth.chmod(0o600)
    with pytest.raises(RuntimeError):
        with agy_job.scratch_home(auth,base=tmp_path) as home:
            copy=home/'.gemini/antigravity-cli/antigravity-oauth-token'
            assert not copy.is_symlink() and copy.read_bytes()==auth.read_bytes()
            assert copy.stat().st_mode&0o777==0o600
            assert (home/'.gemini/config/hooks.json').is_file()
            raise RuntimeError()
    assert not home.exists() and auth.read_text()=='fixture-not-a-token'
    link=tmp_path/'link';link.symlink_to(auth)
    with pytest.raises(ValueError):
        with agy_job.scratch_home(link):pass


def test_unknown_model_group_refuses_instead_of_borrowing_quota():
    assert agy_job.model_group('gemini-3.8-flash-low')=='Gemini Models'
    assert agy_job.model_group('gemini-4-argon-high')=='Gemini 4 Argon'
    with pytest.raises(ValueError):agy_job.model_group('future-model')


def test_stale_or_closed_advisory_does_not_post(tmp_path):
    review={'verdict':'APPROVE','summary':'Test','findings':[]}
    (tmp_path/'review.json').write_text(json.dumps(review))
    head='a'*40
    (tmp_path/'meta.json').write_text(json.dumps({'repo':'example/repo','pr':1,'head':head,'verdict':'APPROVE'}))
    calls=[]
    def run(args,**kw):
        calls.append(args)
        return SimpleNamespace(stdout=json.dumps({'headRefOid':'b'*40,'state':'OPEN'}))
    with pytest.raises(ValueError,match='head moved'):
        agy_job.post_advisory('example/repo',1,head,tmp_path,run=run)
    assert len(calls)==1


def test_zero_quota_refuses_before_spawning_model(tmp_path,monkeypatch):
    from shantytown import agy_usage
    from shantytown.governor import Reading
    auth=tmp_path/'auth';auth.write_text('fixture-only');auth.chmod(0o600)
    monkeypatch.setattr(agy_usage.AgyUsageReader,'read_all',lambda self:{'seven_day':Reading(pct=100,ok=True)})
    monkeypatch.setattr(agy_job.shutil,'which',lambda name:'/fixture/agy')
    monkeypatch.setattr(agy_job.subprocess,'Popen',lambda *args,**kwargs:pytest.fail('exhausted quota spawned a model'))
    with pytest.raises(ValueError,match='exhausted'):
        agy_job.run_review('fixture','gemini-3.8-flash-low',tmp_path/'result',auth=auth,lock_root=tmp_path/'locks')
    assert not (tmp_path/'result/events.ndjson').exists()


def test_declared_agy_review_is_manual_no_retry_and_uses_argv(tmp_path):
    from shantytown import jobs
    spec={'repo':'example/repo','pr':1,'head':'a'*40,'model':'gemini-3.8-flash-low','result_dir':'reviews/one'}
    action=jobs._parse_action(tmp_path/'one.toml',{'agy_review':spec},events=False)
    assert action.kind=='agy-review' and action.command[1:3]==('-m','shantytown.agy_job')
    spec['head']='bad; shell injection'
    with pytest.raises(jobs.JobError):jobs._parse_action(tmp_path/'one.toml',{'agy_review':spec},events=False)


def test_native_refusal_remains_no_verdict_even_with_success_text():
    with pytest.raises(ValueError,match='refusal'):
        agy_job.parse_result(stream(denied_actions=[{'action':'mcp'}]),'gemini-test')
    with pytest.raises(ValueError):agy_job.parse_result('42','gemini-test')


def test_cancelled_job_kills_child_and_removes_temporary_auth(tmp_path,monkeypatch):
    from shantytown import agy_usage
    from shantytown.governor import Reading
    auth=tmp_path/'auth';auth.write_text('fixture-only');auth.chmod(0o600)
    monkeypatch.setattr(agy_usage.AgyUsageReader,'read_all',lambda self:{'seven_day':Reading(pct=0,ok=True)})
    monkeypatch.setattr(agy_job.shutil,'which',lambda name:'/fixture/agy')
    captured={}
    class Child:
        pid=31337
        returncode=None
        def communicate(self,*a,**kw):raise KeyboardInterrupt()
        def poll(self):return self.returncode
        def wait(self,**kw):self.returncode=-9
    def popen(*a,**kw):captured['home']=Path(kw['env']['HOME']);return Child()
    monkeypatch.setattr(agy_job.subprocess,'Popen',popen)
    monkeypatch.setattr(agy_job.os,'killpg',lambda pid,sig:captured.update(killed=pid))
    with pytest.raises(KeyboardInterrupt):
        agy_job.run_review('fixture','gemini-3.8-flash-low',tmp_path/'result',auth=auth,lock_root=tmp_path/'locks')
    assert captured['killed']==31337 and not captured['home'].exists()
    assert auth.read_text()=='fixture-only'
