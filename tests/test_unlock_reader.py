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


def test_targeted_sdk_never_falls_back_or_accepts_foreign_rows(tmp_path,monkeypatch):
    tracker=SdTracker(store=str(tmp_path/'fixture')); calls=[]
    event=dict(event_id='seeds:unlock:example-1:1',issue_id='example-1',assignee='worker',ready_generation=1,observed_at='2026-11-04T19:00:00Z',receipt=None)
    payload={'changed':[],'events':[event]}
    def cli(*args):
        calls.append(args)
        return CompletedProcess(args,0,json.dumps(payload),'')
    monkeypatch.setattr(tracker,'_bd',cli)
    tracker.reconcile_blockers('example-1')
    assert calls[-1]==('blockers','reconcile','example-1','--json')
    assert tracker.unlock_events('example-1').exact()[0]['id']=='example-1'
    assert calls[-1]==('blockers','events','example-1','--json')
    with pytest.raises(ValueError): tracker.unlock_events('other-1')
    payload['changed']=[{'issue_id':'other-1','tx':1}]
    with pytest.raises(ValueError): tracker.reconcile_blockers('example-1')
    for identifier in ['','--all','../other']:
        before=len(calls)
        with pytest.raises(ValueError): tracker.unlock_events(identifier)
        assert len(calls)==before


def test_targeted_reaction_shared_ledger_retains_other_work_and_never_resends(tmp_path):
    from shantytown.unlock_reader import react
    sends=[]; writes=[]; stored=[None]; ack_calls=[]
    event=dict(kind='unlock',id='example-1',episode='seeds:unlock:example-1:1',recipient='worker')
    def reconcile(identifier): writes.append(identifier)
    def events(identifier):
        assert identifier=='example-1'
        return Answer.complete_read([event],how='targeted fixture')
    def ack(identifier,episode,receipt):
        ack_calls.append((identifier,episode,receipt)); stored[0]=receipt
        raise TimeoutError('lost committed ACK response')
    tracker=SimpleNamespace(reconcile_blockers=reconcile,unlock_events=events,
                            unlock_receipt=lambda *args:stored[0],ack_unlock=ack)
    path=tmp_path/'notify'/'overdue.json';path.parent.mkdir()
    due_key=json.dumps(['overdue','other-1','2026-10-01','other'],separators=(',',':'))
    path.write_text(json.dumps({'entries':{due_key:123},'pending':{}}))
    def deliver(*args): sends.append(args);return 'receipt-1'
    assert react(tracker,tmp_path,Registry(),'example-1',deliver=deliver,receipt=lambda *args:None)==['worker']
    assert react(tracker,tmp_path,Registry(),'example-1',deliver=deliver,receipt=lambda *args:None)==[]
    assert len(sends)==1 and len(ack_calls)==1
    assert writes==['example-1','example-1']
    assert json.loads(path.read_text())['entries'][due_key]==123


def test_targeted_reaction_unknown_write_fence_is_per_target(tmp_path):
    writes=[]
    def reconcile(identifier):writes.append(identifier);raise TimeoutError()
    tracker=SimpleNamespace(reconcile_blockers=reconcile,unlock_events=lambda identifier:Answer.complete_read([],how='retained target'))
    first=UnlockReader(tracker,tmp_path,identifier='example-1')
    second=UnlockReader(tracker,tmp_path,identifier='example-2')
    with pytest.raises(TimeoutError):first.events()
    assert first.events().exact()==[]
    with pytest.raises(TimeoutError):second.events()
    assert writes==['example-1','example-2']
    with pytest.raises(ValueError):first.ack('example-2','event','receipt')


def test_targeted_reaction_holds_unrelated_pending_packet_without_reading_or_resending(tmp_path):
    from shantytown.unlock_reader import react
    calls=[]
    key=json.dumps(['unlock','other-1','seeds:unlock:other-1:1',None],separators=(',',':'))
    packet=dict(marker='[overdue:existing]',body='existing',keys=[key],attempted=True)
    path=tmp_path/'notify'/'overdue.json';path.parent.mkdir()
    path.write_text(json.dumps({'entries':{},'pending':{'worker':packet}}))
    tracker=SimpleNamespace(reconcile_blockers=lambda identifier:None,
        unlock_events=lambda identifier:Answer.complete_read([dict(kind='unlock',id=identifier,episode=f'seeds:unlock:{identifier}:1',recipient='worker')],how='fixture'))
    assert react(tracker,tmp_path,Registry(),'example-1',deliver=lambda *args:calls.append('send'),receipt=lambda *args:calls.append('read'))==[]
    assert calls==[]
    assert json.loads(path.read_text())['pending']=={'worker':packet}


def test_targeted_reaction_does_not_poll_due_board_or_ack_other_events(tmp_path):
    calls=[]
    key=json.dumps(['unlock','other-1','seeds:unlock:other-1:1',None],separators=(',',':'))
    evidence=dict(at=123,receipt='prior-receipt',ack='attempted')
    path=tmp_path/'notify'/'overdue.json';path.parent.mkdir()
    path.write_text(json.dumps({'entries':{key:evidence},'pending':{}}))
    a=OverdueAlerter(tmp_path,Registry(),read=lambda:calls.append('due'),
        events=lambda:Answer.complete_read([],how='pending condition; no unlock'),
        deliver=lambda *args:calls.append('send'),ack=lambda *args,**kw:calls.append('ack'),unlock_target='example-1')
    assert a.sweep()==[] and calls==[]
    assert json.loads(path.read_text())['entries'][key]==evidence
