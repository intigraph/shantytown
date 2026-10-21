import json
import subprocess

import pytest

from shantytown.files import FilesTracker
from shantytown.plate_capacity import size
from shantytown.producer_capacity import run, option


def fixture(tmp_path, count):
    tracker = FilesTracker(tmp_path/'items')
    for n in range(count):
        tracker.create(f'work{n}', assignee='worker')
    calls, notices = [], []
    def execute(args):
        calls.append(args)
        owner = option(args, '--assignee', '-a')
        if args[0] == 'create':
            item = tracker.create(args[1], assignee=owner)
        else:
            tracker.update(args[1], assignee=owner or '', status=option(args, '--status'))
            item = tracker.get(args[1])
        return subprocess.CompletedProcess(args, 0, json.dumps({'id': item.id}), '')
    return tracker, calls, notices, execute


def test_full_selected_sdk_producer_preserves_keyed_arguments_routes_pool_notifies(tmp_path):
    tracker, calls, notices, execute = fixture(tmp_path, 10)
    args = ['create','release followup','--assignee','worker','--workflow-run','urn:run',
            '--step','release','--visit','1','--json']
    run(args,tracker,execute,lambda *a:notices.append(a))
    assert len(calls) == 1 and '--assignee' not in calls[0]
    assert calls[0][-7:] == args[-7:]
    assert tracker.get('st-11').assignee is None and size(tracker,'worker') == 10
    assert notices == [('worker','st-11')]


def test_alarm_delivery_does_not_need_capacity_read(tmp_path):
    tracker,calls,notices,execute = fixture(tmp_path,10)
    tracker.capacity_rows = lambda owner: pytest.fail('alarm must not read capacity')
    run(['create','Recurring alarm: fixture','--assignee=worker','--labels','recurring-alarm'],
        tracker,execute,lambda *a:notices.append(a))
    assert len(calls) == 1 and not notices


def test_new_owner_cannot_steal_assigned_work_when_full(tmp_path):
    from shantytown.plate_capacity import PlateFull
    tracker,calls,notices,execute = fixture(tmp_path,10)
    other=tracker.create('another owner',assignee='other')
    with pytest.raises(PlateFull):
        run(['update',other.id,'--assignee','worker'],tracker,execute,lambda *a:None)
    assert calls == [] and tracker.get(other.id).assignee == 'other'


def test_response_lost_after_one_write_is_not_repeated(tmp_path):
    tracker,calls,notices,execute = fixture(tmp_path,9)
    def lost(args):
        execute(args)
        raise TimeoutError()
    with pytest.raises(TimeoutError):
        run(['create','one','--assignee','worker'],tracker,lost,lambda *a:None)
    assert len(calls)==1 and size(tracker,'worker')==10


def test_actual_sdk_child_uses_selected_fixture_store_and_no_real_keys(tmp_path, monkeypatch):
    import os
    from pathlib import Path
    import sys
    sdk=os.environ.get('SCHEDULE_TEST_SD_BIN')
    if not sdk or not Path(sdk).is_absolute():
        pytest.skip('admitted SDK fixture binary not supplied')
    home=tmp_path/'home';home.mkdir()
    root=tmp_path/'crew-root';(root/'crew').mkdir(parents=True)
    (root/'crew'/'worker.json').write_text(json.dumps({'reports_to':'lead'}))
    env=dict(HOME=str(home),XDG_CONFIG_HOME=str(home/'.config'),PATH=os.defpath,
             USER='fixture',SHANTY_ROOT=str(root),PYTHONPATH=str(Path.cwd()))
    def sdk_run(*args):
        return subprocess.run([sdk,*args],cwd=tmp_path,env=env,capture_output=True,text=True,check=True)
    sdk_run('init','--prefix','fixture','--json')
    route=json.loads(sdk_run('where','--json').stdout)
    store=route['database_path']
    assert Path(store).is_relative_to(tmp_path)
    env.update(SHANTY_SD_STORE=store,SHANTY_SD_PREFIX='fixture')
    for n in range(10):
        sdk_run('--store',store,'create',f'work{n}','--assignee','worker','--json')
    payload=dict(binary=sdk,options=['--store',store],timeout=30,
                 arguments=['create','overflow','--assignee','worker','--json'])
    result=subprocess.run([sys.executable,'-m','shantytown.producer_capacity'],
                          input=json.dumps(payload),cwd=tmp_path,env=env,
                          capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    item=json.loads(result.stdout)
    assert item['assignee'] is None
    listed=json.loads(sdk_run('--store',store,'list','--assignee','worker','--limit','0','--json').stdout)
    assert len(listed['issues'])==10
    notices=json.loads(sdk_run('--store',store,'list','--assignee','lead','--limit','0','--json').stdout)
    assert len(notices['issues'])==1 and notices['issues'][0]['title'].startswith('inbox: capacity:')
    alarm=json.loads(sdk_run('--store',store,'create','Recurring alarm: detector',
                            '--assignee','worker','--labels','recurring-alarm','--json').stdout)
    payload['arguments']=['update',alarm['id'],'--title','Implementation','--set-labels','','--json']
    def convert():
        return subprocess.run([sys.executable,'-m','shantytown.producer_capacity'],
                              input=json.dumps(payload),cwd=tmp_path,env=env,
                              capture_output=True,text=True,timeout=30)
    refused=convert()
    assert refused.returncode==2,refused.stderr
    observed=json.loads(sdk_run('--store',store,'show',alarm['id'],'--json').stdout)
    if isinstance(observed,list): observed=observed[0]
    assert observed['title']==alarm['title'] and observed['labels']==alarm['labels']
    sdk_run('--store',store,'close',listed['issues'][0]['id'],'--reason','fixture frees one slot','--json')
    admitted=convert()
    assert admitted.returncode==0,admitted.stderr
    observed=json.loads(sdk_run('--store',store,'show',alarm['id'],'--json').stdout)
    if isinstance(observed,list): observed=observed[0]
    assert observed['title']=='Implementation' and observed['labels']==[]
    label_only=json.loads(sdk_run('--store',store,'create','Detector',
                                 '--assignee','worker','--labels','alarm','--json').stdout)
    payload['arguments']=['update',label_only['id'],'--remove-label','alarm','--json']
    refused=convert()
    assert refused.returncode==2,refused.stderr
    observed=json.loads(sdk_run('--store',store,'show',label_only['id'],'--json').stdout)
    if isinstance(observed,list): observed=observed[0]
    assert observed['labels']==['alarm']
    sdk_run('--store',store,'close',listed['issues'][1]['id'],'--reason','fixture frees one slot','--json')
    admitted=convert()
    assert admitted.returncode==0,admitted.stderr
    observed=json.loads(sdk_run('--store',store,'show',label_only['id'],'--json').stdout)
    if isinstance(observed,list): observed=observed[0]
    assert observed['title']=='Detector' and observed['labels']==[]
    # Pin the SDK's combined replacement/add/remove semantics independently.
    metadata=json.loads(sdk_run('--store',store,'create','metadata','--labels','old','--json').stdout)
    sdk_run('--store',store,'update',metadata['id'],'--set-labels','bug,alarm',
            '--set-labels','enhancement','--add-label','inbox','--remove-label','alarm','--json')
    observed=json.loads(sdk_run('--store',store,'show',metadata['id'],'--json').stdout)
    if isinstance(observed,list): observed=observed[0]
    assert set(observed['labels'])=={'bug','enhancement','inbox'}


def test_full_update_returns_unassigned_item_to_open_pool(tmp_path):
    tracker,calls,notices,execute=fixture(tmp_path,10)
    pool=tracker.create('pool work')
    run(['update',pool.id,'--assignee','worker','--status','in_progress','--json'],
        tracker,execute,lambda *a:notices.append(a))
    assert tracker.get(pool.id).status=='open'
    assert not tracker.get(pool.id).assignee
    assert len(calls)==1 and notices==[('worker',pool.id)]


def test_literal_prose_is_not_an_assignment_flag(tmp_path):
    tracker,calls,notices,execute=fixture(tmp_path,10)
    args=['create','literal','--description','--assignee=other','--assignee','worker','--json']
    run(args,tracker,execute,lambda *a:notices.append(a))
    assert calls[0][calls[0].index('--description')+1]=='--assignee=other'
    assert tracker.get('st-11').assignee is None


def test_unknown_switch_and_bulk_claim_never_bypass_cap(tmp_path):
    tracker,calls,notices,execute=fixture(tmp_path,10)
    for flag in ('--new-sdk-boolean','--claim','--file'):
        with pytest.raises(ValueError):
            run(['create','unsafe',flag,'--assignee','worker'],tracker,execute,lambda *a:None)
    assert not calls



def test_attached_short_options_do_not_bypass_assignment(tmp_path):
    tracker,calls,notices,execute=fixture(tmp_path,10)
    run(['create','short','-aworker','-p1','--json'],tracker,execute,lambda *a:notices.append(a))
    assert tracker.get('st-11').assignee is None and len(notices)==1



def test_explicit_title_overrides_message_prefix_before_admission(tmp_path):
    tracker,calls,notices,execute=fixture(tmp_path,10)
    run(['create','inbox: misleading','--title','real implementation','--assignee','worker','--json'],
        tracker,execute,lambda *a:notices.append(a))
    assert not tracker.get('st-11').assignee and len(notices)==1


@pytest.mark.parametrize('count', [9, 10])
@pytest.mark.parametrize('initial,args,change', [
    ({'title':'Recurring alarm: detector','labels':['recurring-alarm']},
     ['--title','Implementation','--labels',''], {'title':'Implementation','labels':[]}),
    ({'title':'inbox: delivery'}, ['--title','Implementation'], {'title':'Implementation'}),
    ({'title':'Detector','labels':['recurring-alarm']},
     ['--remove-label','recurring-alarm'], {'labels':[]}),
    ({'title':'Detector','labels':['alarm']}, ['--set-labels','bug'], {'labels':['bug']}),
    ({'title':'Detector','labels':['alarm']},
     ['--set-labels','bug','--set-labels','enhancement'], {'labels':['bug','enhancement']}),
    ({'title':'Future','defer_until':'2099-01-01T00:00:00Z'}, ['--defer',''], {'defer_until':''}),
])
def test_sdk_conversion_admission_uses_proposed_membership(tmp_path, count, initial, args, change):
    from shantytown.plate_capacity import PlateFull
    tracker, calls, notices, _ = fixture(tmp_path, count)
    item = tracker.create(assignee='worker', **initial)
    before = tracker._path(item.id).read_bytes()
    def execute(argv):
        calls.append(argv)
        tracker.update(item.id, **change)
        return subprocess.CompletedProcess(argv, 0, json.dumps({'id':item.id}), '')
    if count == 10:
        with pytest.raises(PlateFull):
            run(['update',item.id,*args],tracker,execute,lambda *a:notices.append(a))
        assert calls == [] and tracker._path(item.id).read_bytes() == before
    else:
        run(['update',item.id,*args],tracker,execute,lambda *a:notices.append(a))
        assert len(calls) == 1
    assert size(tracker,'worker') == 10 and tracker.get(item.id).assignee == 'worker'
    assert not notices


def test_sdk_ambiguous_label_edits_refuse_before_write(tmp_path):
    tracker,calls,notices,execute=fixture(tmp_path,10)
    for flags in (['--remove-label','alarm,inbox'], ['--add-label','inbox','--remove-label','inbox']):
        with pytest.raises(ValueError,match='ambiguous producer label'):
            run(['update','st-1',*flags],tracker,execute,lambda *a:None)
    assert not calls
