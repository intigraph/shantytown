from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import json

from shantytown.answer import Answer
from shantytown.overdue import OverdueAlerter
from shantytown import config
from shantytown.seeds_plate import due_rows


class Registry:
    def all(self):
        return Answer.complete_read([SimpleNamespace(name="admin",role="administrator")],how="fixture registry")
    def get(self,name):
        if name not in ("admin","worker"):
            raise LookupError(name)
        return SimpleNamespace(name=name)


def row(identifier="a-1", **kw):
    return dict(id=identifier,title="work",status="open",due_at="2026-10-01T00:00:00Z",assignee="worker",labels=[],**kw)


def test_crossing_digest_daily_restart_and_resolution(tmp_path):
    now=[datetime(2026,10,2,tzinfo=timezone.utc)]
    rows=[row(f"a-{i}") for i in range(112)]
    sent=[]
    kwargs=dict(read=lambda:Answer.complete_read(rows,how="fixture due"),deliver=lambda *args:sent.append(args) or True,now=lambda:now[0])
    def sweep(): return OverdueAlerter(tmp_path,Registry(),**kwargs).sweep()
    assert sweep()==["worker"]
    assert len(sent)==1 and "112" in sent[0][2]
    assert len((sent[0][1]+" "+sent[0][2]).encode())<400
    assert sweep()==[]
    now[0]+=timedelta(hours=23); assert sweep()==[]
    now[0]+=timedelta(hours=1); assert sweep()==["worker"]
    rows.clear(); assert sweep()==[]
    rows.append(row()); assert sweep()==["worker"]


def test_unassigned_messages_and_redate(tmp_path):
    now=datetime(2026,10,2,tzinfo=timezone.utc)
    rows=[dict(row(),assignee=None),dict(row("a-2"),title="inbox: ignored"),dict(row("a-3"),labels=["inbox"])]
    sent=[]
    a=OverdueAlerter(tmp_path,Registry(),read=lambda:Answer.complete_read(rows,how="fixture due"),deliver=lambda *x:sent.append(x) or True,now=lambda:now)
    assert a.sweep()==["admin"]
    assert len(sent)==1 and "1 overdue" in sent[0][2]
    rows[0]["due_at"]="2026-10-01T01:00:00Z"
    assert a.sweep()==["admin"]


def test_unknown_delivery_reconciles_identical_packet_once(tmp_path):
    receipts={}; attempts=[]; now=datetime(2026,10,2,tzinfo=timezone.utc)
    def deliver(who,marker,body):
        attempts.append((who,marker,body))
        if marker in receipts: return True
        receipts[marker]=body
        return False  # committed write followed by unreadable response
    kwargs=dict(read=lambda:Answer.complete_read([row()],how="fixture due"),deliver=deliver,receipt=lambda who,marker:marker in receipts,now=lambda:now)
    assert OverdueAlerter(tmp_path,Registry(),**kwargs).sweep()==[]
    assert OverdueAlerter(tmp_path,Registry(),**kwargs).sweep()==["worker"]
    assert len(attempts)==1 and len(receipts)==1
    assert OverdueAlerter(tmp_path,Registry(),**kwargs).sweep()==[]


def test_unreadable_or_corrupt_state_cannot_authorize_send(tmp_path):
    sent=[]; a=OverdueAlerter(tmp_path,Registry(),read=lambda:Answer.capped([],how="fixture unreadable",caveat="read failed"),deliver=lambda *x:sent.append(x) or True)
    assert a.sweep()==[] and not sent
    a.read=lambda:Answer.complete_read([row()],how="fixture due")
    a.path.write_text("broken")
    assert a.sweep()==[] and not sent


def test_unlock_uses_same_digest_once_per_episode_not_daily(tmp_path):
    now=[datetime(2026,10,2,tzinfo=timezone.utc)]
    events=[dict(id="a-8iq",kind="unlock",episode="condition-revision-1",recipient="worker")]
    sent=[]
    a=OverdueAlerter(tmp_path,Registry(),read=lambda:Answer.complete_read([],how="fixture due"),events=lambda:Answer.complete_read(events,how="fixture unlock"),deliver=lambda *x:sent.append(x) or True,now=lambda:now[0])
    assert a.sweep()==["worker"]
    now[0]+=timedelta(days=2); assert a.sweep()==[]
    events[0]["episode"]="condition-revision-2"; assert a.sweep()==["worker"]
    assert len(sent)==2
    events[0]["recipient"]="admin"; assert a.sweep()==[]  # ordinary owner edit does not create an event
    previous=dict(events[0]); events.clear(); assert a.sweep()==[]
    events.append(previous); assert a.sweep()==[]  # replay after absence stays said


def test_due_projection_positive_and_conflict_unknown(monkeypatch):
    calls=[]; wire=[dict(graph="https://example.org/board",id="a-1",title="work",status="open",due={"datatype":"http://www.w3.org/2001/XMLSchema#dateTime","value":"2026-10-01T00:00:00Z"},assignee="https://seeds.local/principal/worker")]
    def query(proof,text,timeout): calls.append(text); return dict(rows=wire)
    monkeypatch.setattr("shantytown.seeds_plate._query",query)
    proof=SimpleNamespace(graph="https://example.org/board")
    rows=due_rows(proof).exact(); assert len(rows)==1 and rows[0]["assignee"]=="worker"
    assert len(calls)==1 and "2000" in calls[0] and "description" not in calls[0]
    wire.append(dict(wire[0],status="blocked"))
    import pytest
    with pytest.raises(Exception): due_rows(proof).exact()


def test_notifier_config_is_explicit_and_typed(tmp_path):
    path=tmp_path/"shantytown.toml"; path.write_text("[overdue]\nenabled=true\n")
    assert config.load(tmp_path).overdue_enabled
    path.write_text("[overdue]\nenabled='yes'\n")
    import pytest
    with pytest.raises(config.ConfigError): config.load(tmp_path)


def test_unlock_unassigned_and_unknown_delivery_while_condition_changes(tmp_path):
    now=datetime(2026,10,2,tzinfo=timezone.utc)
    events=[dict(id="a-8iq",kind="unlock",episode="1",recipient=None)]
    receipts={}; attempted=[]
    def deliver(who,marker,body):
        attempted.append((who,marker,body)); receipts[marker]=body; return False
    a=OverdueAlerter(tmp_path,Registry(),read=lambda:Answer.complete_read([],how="fixture"),events=lambda:Answer.complete_read(events,how="fixture events"),deliver=deliver,receipt=lambda who,marker:marker in receipts,now=lambda:now)
    assert a.sweep()==[] and attempted[0][0]=="admin"
    events.clear(); assert a.sweep()==["admin"]  # reconcile actual receipt, no send
    events.append(dict(id="a-8iq",kind="unlock",episode="1",recipient=None))
    assert a.sweep()==[] and len(attempted)==1


def test_native_cli_due_reader_accepts_complete_page_and_refuses_cap(tmp_path,monkeypatch):
    from shantytown.sd import SdTracker
    from subprocess import CompletedProcess
    tracker=SdTracker(store=str(tmp_path/"fixture"))
    monkeypatch.setattr(tracker,"_use_remote_projection",lambda:False)
    page={"issues":[row()],"has_more":False,"total":1}
    calls=[]
    def read(*args):
        calls.append(args); return CompletedProcess(args,0,json.dumps(page),"")
    monkeypatch.setattr(tracker,"_bd",read)
    assert tracker.due_rows().exact()[0]["id"]=="a-1"
    assert calls==[("list","--overdue","--json","--limit","0")]
    page["has_more"]=True
    import pytest
    with pytest.raises(ValueError): tracker.due_rows()


def test_absent_receipt_after_ambiguous_attempt_never_resends(tmp_path):
    attempts=[]
    a=OverdueAlerter(tmp_path,Registry(),read=lambda:Answer.complete_read([row()],how="fixture"),deliver=lambda *args:attempts.append(args) or False,receipt=lambda *args:False)
    assert a.sweep()==[]
    assert a.sweep()==[]
    assert a.sweep()==[]
    assert len(attempts)==1
    assert json.loads(a.path.read_text())["pending"]["worker"]["attempted"] is True
