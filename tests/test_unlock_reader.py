import json
from datetime import datetime, timezone
from subprocess import CompletedProcess
from types import SimpleNamespace

import pytest

from shantytown.answer import Answer
from shantytown.overdue import OverdueAlerter, PendingReceipt
from shantytown.sd import SdTracker
from shantytown.unlock_reader import UnlockReader


class Registry:
    def get(self,name): return SimpleNamespace(name=name)


def test_selected_sdk_event_mapping_and_exact_receipt_refusal(tmp_path,monkeypatch):
    tracker=SdTracker(store=str(tmp_path/"fixture")); calls=[]
    event=dict(event_id="seeds:unlock:example-1:1",issue_id="example-1",assignee=None,ready_generation=1,observed_at="2026-10-14T12:00:00Z",receipt=None)
    responses={"events":{"events":[event]},"receipt":{"event":event},"ack":{"tx":123},"reconcile":{"changed":[]}}
    def cli(*args): calls.append(args); return CompletedProcess(args,0,json.dumps(responses[args[1]]),"")
    monkeypatch.setattr(tracker,"_bd",cli)
    assert tracker.unlock_events().exact()==[dict(kind="unlock",id="example-1",episode=event["event_id"],recipient=None)]
    assert tracker.unlock_receipt("example-1",event["event_id"]) is None
    tracker.ack_unlock("example-1",event["event_id"],"receipt-1")
    assert calls[-1]==("blockers","ack","example-1",event["event_id"],"--receipt","receipt-1","--json")
    responses["receipt"]={"event":dict(event,issue_id="foreign")}
    with pytest.raises(ValueError): tracker.unlock_receipt("example-1",event["event_id"])


def test_unknown_reconcile_is_fenced_but_persistent_events_remain_readable(tmp_path):
    calls=[]
    def reconcile(): calls.append("write"); raise TimeoutError()
    tracker=SimpleNamespace(reconcile_blockers=reconcile,unlock_events=lambda:Answer.complete_read([],how="fixture retained"))
    reader=UnlockReader(tracker,tmp_path)
    with pytest.raises(TimeoutError): reader.events()
    assert reader.events().exact()==[] and reader.events().exact()==[]
    assert calls==["write"] and json.loads(reader.path.read_text())["unknown"] is True


def test_ack_readback_precedes_retry_and_conflict_refuses(tmp_path):
    stored=[None]; calls=[]
    def read(*args): calls.append(("read",*args));return stored[0]
    def ack(*args):calls.append(("ack",*args));stored[0]=args[2];raise TimeoutError()
    reader=UnlockReader(SimpleNamespace(unlock_receipt=read,ack_unlock=ack),tmp_path)
    with pytest.raises(TimeoutError): reader.ack("example-1","event-1","receipt-1")
    assert reader.ack("example-1","event-1","receipt-1",attempted=True)
    assert sum(call[0]=="ack" for call in calls)==1
    stored[0]="different"
    with pytest.raises(ValueError):reader.ack("example-1","event-1","receipt-1",attempted=True)


def test_shared_notifier_retains_known_receipt_and_acks_without_resend(tmp_path):
    now=datetime(2026,10,2,tzinfo=timezone.utc); sends=[];acks=[]
    events=[dict(kind="unlock",id="example-1",episode="event-1",recipient="worker")]
    def ack(identifier,event,receipt,*,attempted):
        acks.append((identifier,event,receipt,attempted))
        if len(acks)==1:raise TimeoutError()
        return True
    alerter=OverdueAlerter(tmp_path,Registry(),read=lambda:Answer.complete_read([],how="fixture due"),events=lambda:Answer.complete_read(events,how="fixture events"),deliver=lambda *args:sends.append(args) or "receipt-1",ack=ack,now=lambda:now)
    assert alerter.sweep()==["worker"]
    assert alerter.sweep()==[]
    assert len(sends)==1 and acks==[("example-1","event-1","receipt-1",False),("example-1","event-1","receipt-1",True)]
    assert alerter.sweep()==[] and len(acks)==2


def test_known_id_reconciles_by_exact_id_before_event_ack(tmp_path):
    sends=[];reads=[];acks=[]
    def receipt(who,marker,identifier=None):reads.append(identifier);return identifier
    events=[dict(kind="unlock",id="example-1",episode="event-1",recipient="worker")]
    a=OverdueAlerter(tmp_path,Registry(),read=lambda:Answer.complete_read([],how="fixture"),events=lambda:Answer.complete_read(events,how="fixture"),deliver=lambda *args:sends.append(args) or PendingReceipt("known-1"),receipt=receipt,ack=lambda *args,**kw:acks.append(args) or True)
    assert a.sweep()==[]
    assert a.sweep()==["worker"]
    assert len(sends)==1 and reads==["known-1"] and acks==[("example-1","event-1","known-1")]


def test_unknown_unlock_reader_does_not_silence_known_overdue_work(tmp_path):
    sends=[]
    def failed():raise TimeoutError()
    row=dict(id="example-1",title="work",status="open",due_at="2026-10-01",assignee="worker",labels=[])
    a=OverdueAlerter(tmp_path,Registry(),read=lambda:Answer.complete_read([row],how="fixture due"),events=failed,deliver=lambda *args:sends.append(args) or "receipt-1",now=lambda:datetime(2026,10,2,tzinfo=timezone.utc))
    assert a.sweep()==["worker"] and len(sends)==1


def test_inbox_receipt_binds_exact_id_recipient_label_and_marker():
    from shantytown.overdue import verify_inbox_receipt
    value=dict(id="receipt-1",assignee="worker",labels=["inbox"],title="inbox: [overdue:abc] fixture",status="closed")
    assert verify_inbox_receipt(value,"worker","[overdue:abc]","receipt-1")=="receipt-1"
    for changed in [dict(id="foreign"),dict(assignee="other"),dict(labels=[]),dict(title="inbox: different marker")]:
        with pytest.raises(ValueError): verify_inbox_receipt(dict(value,**changed),"worker","[overdue:abc]","receipt-1")
