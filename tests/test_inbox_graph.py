"""Message scope must not become a work-board override or lose legacy receipts."""
import json
import os
import shutil
import subprocess
from argparse import Namespace
from pathlib import Path

import pytest

from shantytown import cli
from shantytown.br import items, BrTracker
from shantytown.inbox import TrackerInbox
from shantytown.sd import SdTracker, StoreProof, StoreUnproven, br_like_tracker

BOARD = 'https://tracker.example/board'
INBOX = BOARD+'/inbox'

# Save entrypoints before the suite replaces every transport with its live-store
# refusal. The terminal fake below is installed BEFORE restoring these bodies.
_REAL_PROVE = SdTracker.prove_store
_REAL_IN = SdTracker._bd_in
_REAL_BD = BrTracker._bd


def tracker(**overrides):
    values = dict(quipu='https://graph.example', prefix='work',
                  inbox_graph=INBOX, inbox_prefix='messages')
    return SdTracker(**(values | overrides))


def fake_sdk(monkeypatch, *, wrong_inbox_graph=False):
    calls = []
    def run(cmd, **options):
        env = options.get('env') or os.environ
        graph = cmd[cmd.index('--graph')+1] if '--graph' in cmd else BOARD
        prefix = env.get('SEEDS_PREFIX', 'work')
        calls.append((list(cmd), graph, prefix))
        if 'where' in cmd:
            result = dict(location_source='--quipu', quipu_url='https://graph.example',
                          graph=BOARD if wrong_inbox_graph and graph==INBOX else graph,
                          prefix=prefix)
        elif 'create' in cmd:
            result = dict(id=prefix+'-new')
        else:
            raise AssertionError('unexpected fixture SDK operation')
        return subprocess.CompletedProcess(cmd, 0, json.dumps(result), '')
    monkeypatch.setattr(subprocess, 'run', run)
    monkeypatch.setattr(SdTracker, 'prove_store', _REAL_PROVE)
    monkeypatch.setattr(SdTracker, '_bd_in', _REAL_IN)
    monkeypatch.setattr(BrTracker, '_bd', _REAL_BD)
    return calls


def test_unconfigured_inbox_keeps_existing_adapter_without_a_read():
    value = tracker(inbox_graph=None, inbox_prefix=None)
    assert value.inbox_tracker() is value


@pytest.mark.parametrize('values', [dict(inbox_graph=None), dict(inbox_prefix=None),
                                    dict(inbox_prefix='work'), dict(inbox_prefix='bad prefix')])
def test_partial_or_shared_id_scope_refuses_before_any_sdk_call(monkeypatch, values):
    calls = fake_sdk(monkeypatch)
    with pytest.raises(StoreUnproven):
        tracker(**values).create('inbox: cannot lose this')
    assert calls == []


@pytest.mark.parametrize("graph", [BOARD, BOARD+"#seeds-ephemeral"])
def test_same_graph_refuses_after_work_identity_proof_without_writing(monkeypatch,graph):
    calls = fake_sdk(monkeypatch)
    with pytest.raises(StoreUnproven):
        tracker(inbox_graph=graph).create('inbox: independent graph required')
    assert len(calls)==1 and 'where' in calls[0][0]


@pytest.mark.parametrize("unsafe", [INBOX+'> UNION {', "http://["])
def test_unsafe_graph_refuses_before_any_write(monkeypatch,unsafe):
    calls = fake_sdk(monkeypatch)
    with pytest.raises(StoreUnproven, match='invalid configured inbox graph'):
        tracker(inbox_graph=unsafe).create('inbox: exact scope only')
    assert len(calls)==1 and 'where' in calls[0][0]


def test_wrong_graph_readback_never_falls_back_or_creates(monkeypatch):
    calls = fake_sdk(monkeypatch, wrong_inbox_graph=True)
    with pytest.raises(StoreUnproven, match='configured inbox graph'):
        tracker().create('inbox: guarded destination')
    assert len(calls)==2 and all('where' in c[0] for c in calls)


def test_message_and_work_create_use_distinct_scopes_and_allocation(monkeypatch):
    calls = fake_sdk(monkeypatch)
    value = tracker()
    message = value.create('inbox: capacity notification', assignee='worker')
    work = value.create('real work', assignee='worker')
    assert message.id=='messages-new' and work.id=='work-new'
    effects = [c for c in calls if 'create' in c[0]]
    assert [(graph,prefix) for _,graph,prefix in effects]==[(INBOX,'messages'),(BOARD,'work')]
    assert '--graph' not in effects[1][0]
    assert value.prove_store().graph==BOARD


def test_cli_inbox_reader_selects_the_same_scoped_tracker(monkeypatch):
    fake_sdk(monkeypatch)
    value = tracker()
    monkeypatch.setattr(cli, '_backend', lambda *a, **k:'seeds')
    monkeypatch.setattr(cli, '_tracker', lambda *a, **k:value)
    box = cli._inbox(Namespace())
    assert box._tracker is value.inbox_tracker()
    assert box._items_for.__self__ is box._tracker
    assert box._tracker.prove_store().graph==INBOX


def test_deployment_getter_passes_both_scope_fields_without_changing_work_location():
    values={'SHANTY_BACKEND':'seeds','SHANTY_SD_QUIPU':'https://graph.example',
            'SHANTY_SD_PREFIX':'work','SHANTY_SD_INBOX_GRAPH':INBOX,
            'SHANTY_SD_INBOX_PREFIX':'messages'}
    value=br_like_tracker(values.get)
    assert value._location()==['--quipu','https://graph.example']
    assert (value.inbox_graph,value.inbox_prefix)==(INBOX,'messages')


@pytest.mark.real_store
@pytest.mark.skipif(shutil.which('sd') is None, reason='native Seeds unavailable')
def test_native_old_prefix_receipts_and_new_ids_coexist_without_work_leak(tmp_path,monkeypatch):
    # Explicit private HOME, project and store; never a deployment lookup.
    home=tmp_path/'home';home.mkdir();monkeypatch.setenv('HOME',str(home))
    project=tmp_path/'project';project.mkdir();database=tmp_path/'private.db'
    binary=shutil.which('sd')
    def sdk(graph,*args):
        result=subprocess.run([binary,'--store',str(database),'--graph',graph,*args],
                              cwd=project,capture_output=True,text=True,check=True,timeout=30)
        return json.loads(result.stdout)
    subprocess.run([binary,'init','--prefix','work'],cwd=project,capture_output=True,
                   text=True,check=True,timeout=30)
    config=project/'.seeds/config.toml'
    config.write_text('[project]\nprefix = "work"\ngraph = "'+BOARD+'"\n')
    control=sdk(BOARD,'create','real work control','--json')
    legacy=sdk(INBOX,'create','inbox: [receipt:legacy] retained','-a','worker','-l','inbox','--json')
    value=SdTracker(repo=str(project),store=str(database),prefix='work',
                    inbox_graph=INBOX,inbox_prefix='messages')
    scoped=value.inbox_tracker()
    box=TrackerInbox(scoped,lambda:items(scoped),items_for=scoped.inbox_items)
    new=box.deliver('worker','[receipt:new] retained')
    assert new.id.startswith('messages-') and legacy['id'].startswith('work-')
    assert {m.id for m in box.unread('worker')}=={legacy['id'],new.id}
    assert box.find_delivery('worker','[receipt:legacy]').id==legacy['id']
    assert [m.id for m in box.mark_read('worker',[legacy['id']])]==[legacy['id']]
    assert box.find_delivery('worker','[receipt:legacy]').read
    assert {m.id for m in box.unread('worker')}=={new.id}
    work=sdk(BOARD,'list','--limit','5','--json')
    rows=work.get('issues',work) if isinstance(work,dict) else work
    assert [r['id'] for r in rows]==[control['id']]
    assert value.get(control['id']).status=='open'


@pytest.mark.parametrize('backend', ['beads', 'br'])
def test_other_backends_do_not_probe_seeds_inbox_scope(monkeypatch,backend):
    class OtherTracker:
        def __getattr__(self,name):
            if name=='inbox_tracker':
                pytest.fail('Seeds scope must not be requested on another adapter')
            raise AttributeError(name)
    value=OtherTracker()
    monkeypatch.setattr(cli,'_backend',lambda *a,**k:backend)
    monkeypatch.setattr(cli,'_tracker',lambda *a,**k:value)
    assert cli._inbox(Namespace())._tracker is value


@pytest.mark.parametrize('separate', [False,True])
def test_sdk_capacity_notice_uses_same_message_scope(monkeypatch,separate):
    import io
    from shantytown import producer_capacity,files
    calls=fake_sdk(monkeypatch)
    monkeypatch.setenv('SHANTY_SD_QUIPU','https://graph.example')
    monkeypatch.setenv('SHANTY_SD_PREFIX','work')
    monkeypatch.setenv('SHANTY_ROOT','/fixture')
    monkeypatch.setenv('SHANTY_SD_INBOX_GRAPH',INBOX if separate else '')
    monkeypatch.setenv('SHANTY_SD_INBOX_PREFIX','messages' if separate else '')
    monkeypatch.delenv('SHANTY_SD_STORE',raising=False)
    monkeypatch.setattr(files,'FilesRegistry',lambda *a:Namespace(get=lambda owner:Namespace(reports_to='lead')))
    def retained(arguments,tracker,execute,notify):
        notify('worker','work-retained')
        return subprocess.CompletedProcess(arguments,0,'{}','')
    monkeypatch.setattr(producer_capacity,'run',retained)
    monkeypatch.setattr(producer_capacity.sys,'stdin',io.StringIO(json.dumps({
        'binary':'/fixture/sd','options':[],
        'arguments':['create','work','--assignee','worker'],'timeout':10})))
    assert producer_capacity.main()==0
    effects=[entry for entry in calls if 'create' in entry[0]]
    assert len(effects)==1
    assert effects[0][1:]==((INBOX,'messages') if separate else (BOARD,'work'))
