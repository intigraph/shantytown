import json
import shlex
from pathlib import Path
from types import SimpleNamespace

import pytest

from shantytown.harness import get, running_name
from shantytown.protocols import Agent
from shantytown import agy, agy_hooks


def test_launch_identity_and_settings_are_not_sniffed_as_claude(tmp_path):
    card=Agent('local', harness='agy', workspace='/workspace with spaces', model='gemini-test')
    config=tmp_path/'settings with spaces.json'
    line=get('agy').launch(card,str(config),root=tmp_path)
    assert get('agy').carries_settings(line,str(config))
    assert get('claude').settings_in_cmdline(line) is None
    assert running_name(line)=='agy'
    assert '--sandbox' in line and '--dangerously-skip-permissions' not in line
    assert '--model gemini-test' in line
    assert 'SHANTY_AGENT=local' in line
    assert get('agy').settings_in_cmdline('claude --settings /elsewhere') is None


def test_unproven_router_and_missing_workspace_refuse(tmp_path):
    from shantytown.runtime import require_capability, CapabilityError
    from shantytown.harness import Unsupported
    with pytest.raises(CapabilityError):
        require_capability(get('agy'),Agent('local',role='lead'))
    with pytest.raises(Unsupported):
        get('agy').launch(Agent('local'),str(tmp_path/'settings.json'))


def test_hooks_are_separate_private_idempotent_and_preserve_user(tmp_path):
    config=tmp_path/'settings.json'
    config.write_text(get('agy').render(get('agy').settings('worker',tmp_path)))
    assert json.loads(config.read_text())['useG1Credits'] is False
    assert get('agy').read_stop_directions(config.read_text())=={'send'}
    ws=tmp_path/'workspace';ws.mkdir();(ws/'.agents').mkdir()
    path=ws/'.agents/hooks.json';path.write_text('{"personal":{}}')
    agy.project_hooks(ws,config)
    first=path.read_bytes();agy.project_hooks(ws,config)
    assert first==path.read_bytes()
    assert json.loads(first)['personal']=={}
    assert path.stat().st_mode&0o777==0o600
    path.write_text('malformed')
    with pytest.raises(Exception,match='preserved'):agy.project_hooks(ws,config)
    assert path.read_text()=='malformed'


def test_native_write_file_cannot_escape_edit_matcher():
    payload=agy_hooks.translated('PreToolUse',{'toolCall':{'name':'write_file','args':{'Path':'/fixture','Content':'text'}}})
    assert payload['tool_name']=='Write'
    assert payload['tool_input']=={'file_path':'/fixture','content':'text'}
    with pytest.raises(ValueError):
        agy_hooks.translated('PreToolUse',{'toolCall':{'name':'call_mcp_tool','args':{}}})


def config(tmp_path,event,command='fixture'):
    path=tmp_path/'settings.json'
    path.write_text(json.dumps({'hooks':{event:[{'hooks':[{'command':command}]}]}}))
    return path


def test_guard_failures_are_denied_and_native_identity_is_used(tmp_path,monkeypatch):
    monkeypatch.setenv('QUIPU_SESSION','stale-parent')
    monkeypatch.setenv('QUIPU_MODEL','stale-model')
    def runner(command,payload,timeout,env):
        assert env['QUIPU_HARNESS']=='agy'
        assert env['QUIPU_SESSION']=='native-session'
        assert env['QUIPU_MODEL']=='served-model'
        return 2,'','denied fixture'
    answer=agy_hooks.dispatch('PreToolUse',{'conversationId':'native-session','modelName':'served-model',
          'toolCall':{'name':'run_command','args':{'CommandLine':'echo safe'}}},config(tmp_path,'PreToolUse'),runner=runner)
    assert answer=={'decision':'deny','reason':'denied fixture'}


@pytest.mark.parametrize('reason,idle,continues',[('NO_TOOL_CALL',True,True),('ERROR',True,False),
                                                 ('USER_CANCELED',True,False),('NO_TOOL_CALL',False,False)])
def test_stop_continues_only_normal_idle(tmp_path,reason,idle,continues):
    answer=agy_hooks.dispatch('Stop',{'terminationReason':reason,'fullyIdle':idle},config(tmp_path,'Stop'),
                              runner=lambda *a:(0,'{"decision":"block","reason":"next work"}',''))
    assert (answer.get('decision')=='continue') is continues


def test_native_receipt_binds_both_artifacts(tmp_path,monkeypatch):
    monkeypatch.setenv('SHANTY_ROOT',str(tmp_path));monkeypatch.setenv('SHANTY_AGENT','local')
    monkeypatch.setattr(agy_hooks,'native_process',lambda:(999,'fixture-agy'))
    monkeypatch.setattr(agy,'process_identity',lambda pid:'fixture-agy')
    path=config(tmp_path,'SessionStart');ws=tmp_path/'ws';ws.mkdir();agy.project_hooks(ws,path)
    agy_hooks.dispatch('SessionStart',{'conversationId':'native','workspacePaths':[str(ws)]},path,
                       runner=lambda *a:(0,'',''))
    assert agy.receipt_matches(tmp_path,'local',path,ws)
    path.write_text('{}')
    assert not agy.receipt_matches(tmp_path,'local',path,ws)


def test_usage_groups_are_explicit_and_exhaustion_is_not_borrowed():
    from shantytown.agy_usage import AgyUsageReader
    data={'status':'SUCCESS','num_turns':0,'command':{'name':'usage','data':{'groups':[
        {'name':'General','buckets':[{'window':'weekly','remaining_fraction':1,'reset_time':'2030-01-01T00:00:00Z'}]},
        {'name':'Argon','buckets':[{'window':'weekly','remaining_fraction':0,'reset_time':'2030-01-01T00:00:00Z'}]}]}}}
    run=lambda *a,**kw:SimpleNamespace(returncode=0,stdout=json.dumps(data))
    assert AgyUsageReader('seven_day','Argon',run=run).read().pct==100
    assert AgyUsageReader('seven_day','General',run=run).read().pct==0
    assert AgyUsageReader('seven_day',None,run=run).read().ok is False
    data['command']['data']['groups'][1]['buckets'][0]['remaining_fraction']=True
    assert AgyUsageReader('seven_day','Argon',run=run).read().ok is False


def test_inherited_agy_provision_uses_workspace_hooks_and_mcp(tmp_path):
    from shantytown import provision
    (tmp_path/'shantytown.toml').write_text('[harness]\ndefault="agy"\n')
    ws=tmp_path/'ws';ws.mkdir();(ws/'CLAUDE.md').write_text('shared instructions')
    program=get('agy');path=tmp_path/'settings'/program.settings_name('worker')
    path.parent.mkdir(parents=True);path.write_text(program.render(program.settings('worker',tmp_path)))
    kit=tmp_path/'provision';kit.mkdir()
    (kit/'mcp.template.json').write_text(json.dumps({'mcpServers':{'local':{'command':'example','args':[]}}}))
    (kit/'settings.local.json').write_text('{}')
    assert provision.provision(Agent('local',workspace=str(ws)),tmp_path,settings_path=str(path))==['local']
    assert json.loads((ws/'.agents/hooks.json').read_text())['shantytown']['SessionStart']
    assert json.loads((ws/'.agents/mcp_config.json').read_text())['mcpServers']['local']['command']=='example'
    assert (ws/'AGENTS.md').read_text()=='shared instructions'


def test_runtime_live_wiring_refuses_missing_native_receipt(tmp_path):
    from shantytown.runtime import live_wiring
    path=tmp_path/'settings.json'
    path.write_text(get('agy').render(get('agy').settings('worker',tmp_path)))
    line=get('agy').launch(Agent('local',harness='agy',workspace=str(tmp_path)),str(path),root=tmp_path)
    assert live_wiring('local',lambda pane:line) is None


def test_native_mcp_identity_requires_exact_workspace_server(tmp_path):
    (tmp_path/'.agents').mkdir()
    (tmp_path/'.agents/mcp_config.json').write_text('{"mcpServers":{"canary":{}}}')
    native={'workspacePaths':[str(tmp_path)],'toolCall':{'name':'call_mcp_tool','args':{
        'ServerName':'canary','ToolName':'read_fixture','Arguments':{'id':1}}}}
    payload=agy_hooks.translated('PreToolUse',native)
    assert payload['tool_name']=='mcp__canary__read_fixture'
    assert payload['tool_input']=={'id':1}
    native['toolCall']['args']['ServerName']='unconfigured'
    with pytest.raises(ValueError):agy_hooks.translated('PreToolUse',native)
