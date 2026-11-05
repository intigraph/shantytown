"""Measured CLI updates prefer checkpointed replacement, never busy execution."""
import io
import json
from types import SimpleNamespace

from shantytown import cycle_advice as ca, runtime_update as update, stop_policy
from shantytown.protocols import Agent


def world(tmp_path, version="2.1.317"):
    card=Agent(name="reader",role="administrator",harness="claude",workspace=str(tmp_path))
    transcript=tmp_path/"session.jsonl"
    transcript.write_text(json.dumps(dict(type="api-request",sessionId="exact",version=version))+"\n")
    return card,dict(session_id="exact",transcript_path=str(transcript))


def test_native_metadata_is_exact_bounded_and_never_message_content(tmp_path):
    card,payload=world(tmp_path)
    path=tmp_path/"session.jsonl"
    assert update.running_version(path,"exact")=="2.1.317"
    with path.open("a") as out:
        out.write(json.dumps(dict(message=dict(version="99.0.0")))+"\n")
        out.write(json.dumps(dict(isSidechain=True,sessionId="side",version="99.0.0"))+"\n")
    assert update.running_version(path,"exact")=="2.1.317"
    with path.open("a") as out:
        out.write(json.dumps(dict(sessionId="other",version="2.1.318"))+"\n")
    assert update.running_version(path,"exact") is None
    path.write_text('{}\n'*100000+json.dumps(dict(sessionId="exact",version="2.1.318"))+"\n")
    assert update.running_version(path,"exact")=="2.1.318"
    path.write_text(json.dumps(dict(sessionId="exact",version="2.1.318"))+"\n"+'{}\n'*100000)
    assert update.running_version(path,"exact") is None


def test_installed_probe_is_cached_and_identity_changes_recheck(tmp_path, monkeypatch):
    binary=tmp_path/"claude"
    binary.write_text("first executable")
    monkeypatch.setattr(update.shutil,"which",lambda name:str(binary))
    calls=[]
    def run(args,**kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0,stdout=f"2.1.{317+len(calls)} (Claude Code)\n")
    monkeypatch.setattr(update.subprocess,"run",run)
    assert update.installed_version(tmp_path)=="2.1.318"
    assert update.installed_version(tmp_path)=="2.1.318"
    assert len(calls)==1
    binary.write_text("replacement executable with a new identity")
    assert update.installed_version(tmp_path)=="2.1.319"
    assert len(calls)==2
    assert calls[0]==[str(binary),"--version"]


def test_racing_update_and_bad_probe_do_not_become_installed_versions(tmp_path, monkeypatch):
    binary=tmp_path/"claude";binary.write_text("old")
    monkeypatch.setattr(update.shutil,"which",lambda name:str(binary))
    def race(*args,**kwargs):
        binary.write_text("new identity")
        return SimpleNamespace(returncode=0,stdout="2.1.318 (Claude Code)\n")
    monkeypatch.setattr(update.subprocess,"run",race)
    assert update.installed_version(tmp_path) is None
    monkeypatch.setattr(update.subprocess,"run",lambda *a,**k:SimpleNamespace(returncode=1,stdout="2.1.318 (Claude Code)"))
    assert update.installed_version(tmp_path) is None
    assert not update.newer(None,"2.1.318")
    assert not update.newer("unknown","2.1.318")
    assert not update.newer("2.1.318-beta","2.1.319")
    assert not update.newer("2.1.318","2.1.317")


def test_actual_stop_path_emits_once_and_requires_replacement_checkpoint(tmp_path, monkeypatch, capsys):
    card,payload=world(tmp_path)
    monkeypatch.setattr(update,"installed_version",lambda root:"2.1.318")
    monkeypatch.setattr("sys.stdin",io.StringIO(json.dumps(payload)))
    assert stop_policy.stop_advice(tmp_path,card)
    result=json.loads(capsys.readouterr().out)
    assert "running 2.1.317, installed 2.1.318" in result["reason"]
    assert "--self --no-in-place --checkpoint-file" in result["reason"]
    assert "do not interrupt active work" in result["reason"]
    assert not (tmp_path/"notify/cycle-requests.json").exists()
    monkeypatch.setattr("sys.stdin",io.StringIO(json.dumps(payload)))
    assert not stop_policy.stop_advice(tmp_path,card)
    assert capsys.readouterr().out==""


def test_missing_or_unselected_running_evidence_never_probes_or_cycles(tmp_path, monkeypatch):
    card,payload=world(tmp_path)
    def forbidden(*args):raise AssertionError("no installed probe without native running evidence")
    monkeypatch.setattr(update,"installed_version",forbidden)
    assert not update.observe(tmp_path,card,dict(payload,session_id="other")).outdated
    from dataclasses import replace
    card=replace(card,harness="codex")
    assert not update.observe(tmp_path,card,payload).outdated
    assert not update.for_agent(tmp_path,"../reader").outdated


def test_version_preference_honors_manual_keep_and_hard_context_limits():
    sit=ca.Situation("reader",80,350,now=1000,running_version="2.1.317",
                     installed_version="2.1.318",session_id="exact")
    advice=ca.decide(sit,None)
    assert advice.decision==ca.CYCLE and advice.restart_required
    assert advice.runtime_version_key=="exact:2.1.317->2.1.318"
    assert not ca.should_ask(sit,ca.Policy())
    keep=ca.Signal("operator",1000,decision=ca.KEEP)
    assert ca.decide(sit,keep).decision==ca.KEEP
    from dataclasses import replace
    hard=ca.decide(replace(sit,depth_k=360),keep)
    assert hard.decision==ca.CYCLE and hard.restart_required
    assert ca.decide(replace(sit,running_version=None),None).decision==ca.DEFAULT
    assert ca.decide(replace(sit,installed_version="2.1.316"),None).decision==ca.DEFAULT
    assert ca.decide(replace(sit,session_id=""),None).decision==ca.DEFAULT


def test_version_only_cycle_advisor_needs_no_tracker_query(tmp_path, monkeypatch):
    from shantytown import cli
    monkeypatch.setattr(update,"for_agent",lambda *a:update.Evidence("exact","2.1.317","2.1.318"))
    def forbidden(*args):raise AssertionError("version-only preference must not query the plate or model")
    monkeypatch.setattr(cli,"_advise_situation",forbidden)
    advice=cli._cycle_advisor(SimpleNamespace(root=tmp_path))("reader",20)
    assert advice.decision==ca.CYCLE and advice.restart_required
    monkeypatch.setattr(update,"for_agent",lambda *a:update.Evidence("exact","2.1.318","2.1.318"))
    assert cli._cycle_advisor(SimpleNamespace(root=tmp_path))("reader",20) is None


def test_pending_cycle_or_fresh_manual_keep_defers_stop_reminder(tmp_path, monkeypatch, capsys):
    from shantytown.cycle import Requests
    card,payload=world(tmp_path)
    monkeypatch.setattr(update,"installed_version",lambda root:"2.1.318")
    monkeypatch.setattr(update.time,"time",lambda:1000)
    requests=Requests(tmp_path)
    requests.request(card.name,"existing checkpoint",no_in_place=True)
    assert not update.emit(tmp_path,card,payload)
    assert requests.pending()[card.name]["no_in_place"] is True
    requests.clear(card.name)
    ca.post(tmp_path,card.name,ca.Signal("operator",1000,decision=ca.KEEP))
    assert not update.emit(tmp_path,card,payload)
    ca.clear(tmp_path,card.name)
    requests.path.write_text("malformed")
    assert not update.emit(tmp_path,card,payload)
    requests.path.unlink()
    assert update.emit(tmp_path,card,payload)
    assert "RUNTIME UPDATE" in capsys.readouterr().out


def test_version_metadata_before_relaunch_or_without_timestamp_is_unknown(tmp_path):
    path=tmp_path/"native.jsonl"
    path.write_text(json.dumps(dict(sessionId="exact",version="2.1.317"))+"\n")
    assert update.running_version(path,"exact",not_before=1000) is None
    path.write_text(json.dumps(dict(sessionId="exact",version="2.1.317",timestamp="1970-01-01T00:16:39Z"))+"\n")
    assert update.running_version(path,"exact",not_before=1000) is None
    path.write_text(json.dumps(dict(sessionId="exact",version="2.1.317",timestamp="1970-01-01T00:16:41Z"))+"\n")
    assert update.running_version(path,"exact",not_before=1000)=="2.1.317"


def test_pending_cycle_precedes_stdin_and_all_advice(tmp_path, monkeypatch, capsys):
    from shantytown import cycle, context_hint, ruling_memory
    card, _ = world(tmp_path)
    cycle.Requests(tmp_path).request(card.name, 'saved checkpoint')
    def forbidden(*args, **kwargs):
        raise AssertionError('pending cycle must precede stdin and advice')
    monkeypatch.setattr(stop_policy.json, 'load', forbidden)
    monkeypatch.setattr(ruling_memory, 'enabled', forbidden)
    monkeypatch.setattr(context_hint, 'emit', forbidden)
    monkeypatch.setattr(update, 'emit', forbidden)
    assert stop_policy.stop_advice(tmp_path, card)
    assert capsys.readouterr().out == ''


def test_advice_order_after_pending_cycle_check(tmp_path, monkeypatch):
    from shantytown import context_hint, ruling_memory
    card, payload = world(tmp_path)
    calls=[]
    monkeypatch.setattr('sys.stdin', io.StringIO(json.dumps(payload)))
    monkeypatch.setattr(ruling_memory, 'enabled', lambda root: True)
    monkeypatch.setattr(ruling_memory, 'check', lambda *args: calls.append('memory'))
    monkeypatch.setattr(context_hint, 'emit', lambda *args, **kwargs: calls.append('context'))
    monkeypatch.setattr(update, 'emit', lambda *args: calls.append('update'))
    assert not stop_policy.stop_advice(tmp_path, card)
    assert calls == ['memory', 'context', 'update']
