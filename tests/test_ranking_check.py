from datetime import datetime,timezone
from types import SimpleNamespace

import pytest

from shantytown import ranking_check as ranking
from shantytown.answer import Answer
from shantytown.protocols import Agent


def work(ident,priority=1,**extra):
    return {"id":ident,"title":ident,"status":"open","priority":priority,"labels":[],**extra}


def test_digest_names_every_live_lower_plate_and_every_unowned_p0_without_mutation():
    cards=[Agent(name=n,pane=n) for n in ("a","b","down")]
    rows=[work("a-active",2,assignee="a",status="in_progress"),
          work("a-open",0,assignee="a"),work("b-active",1,assignee="b",status="in_progress"),
          work("down-active",3,assignee="down",status="in_progress"),work("urgent",0),
          work("p0-wait",0,status="deferred"),work("owned",0,assignee="other"),
          work("message",0,title="inbox: message")]
    before=repr(rows)
    text,actionable=ranking.digest([rows[4],rows[6]],rows,cards,{"a","b"},counts="P0 created 4, closed 2")
    assert "a: a-active P2" in text and "b: b-active P1" in text
    assert "down:" not in text and "unowned P0: p0-wait, urgent" in text
    assert "below unowned READY urgent" in text and "READY owned" not in text
    assert actionable and repr(rows)==before
    assert "no auto-reassignment" in text


def test_equal_priority_and_owned_waiters_never_invent_priority_violation():
    rows=[work("held",0,assignee="a",status="in_progress"),work("same",0),work("owned",0,assignee="b")]
    text,_=ranking.digest(rows[1:],rows,[Agent(name="a")],{"a"},counts="counts")
    assert "no proven live-agent priority mismatch" in text


def controls():
    return [{"metric":"coverage","value":1},{"metric":"aggregation_control","value":1}]


def test_counts_reconcile_work_separately_from_inbox_and_disclose_calendar_window():
    rows=controls()+[
        {"metric":"created","priority":"0","kind":"work","value":5,"day":"2026-10-25"},
        {"metric":"created","priority":"0","kind":"inbox","value":20,"day":"2026-10-25"},
        {"metric":"created_total","value":25},
        {"metric":"closed","priority":"0","kind":"work","value":3,"day":"2026-10-20"},
        {"metric":"closed_total","value":3}]
    calls=[]
    def reader(root,name,params,**kw):calls.append(params);return rows
    text=ranking.cohorts(None,now=datetime(2026,10,25,15,tzinfo=timezone.utc),reader=reader)
    assert "created 5, closed 3" in text and "2026-10-19..2026-10-25" in text
    assert calls[0]['day00'] < calls[0]['day31']


@pytest.mark.parametrize("rows",[[],[{"metric":"coverage","value":1}],
                                  controls()+[{"metric":"created_total","value":7}],
                                  controls()+[{"metric":"invalid","value":1,"invalid":1}]])
def test_failed_controls_or_unreconciled_counts_are_unknown(rows):
    with pytest.raises(ValueError):ranking.cohorts(None,reader=lambda *a,**k:rows)


def test_report_preserves_unknown_counts_instead_of_zero():
    cards=[Agent(name="a",pane="p")]
    reg=SimpleNamespace(all=lambda:Answer.complete_read(cards,how="fixture"))
    def fail(root):raise OSError("down")
    text,_,actionable=ranking.report(None,[],[],reg,SimpleNamespace(exists=lambda p:True),counts_reader=fail)
    assert "counts UNKNOWN" in text and "created 0" not in text and actionable


def test_actual_tend_digest_routes_once_to_administrator_and_changes_no_items(tmp_path):
    cards=[Agent(name="chief",role="administrator",pane="chief"),Agent(name="worker",pane="worker")]
    reg=SimpleNamespace(all=lambda:Answer.complete_read(cards,how="fixture"))
    panes=SimpleNamespace(exists=lambda p:True)
    rows=[work("active",2,assignee="worker",status="in_progress"),work("urgent",0)]
    before=repr(rows);sent=[];logs=[]
    def push(reg,panes,text):sent.append(("chief",text));return "chief"
    def counts(root):return "P0 work, 7 UTC dates: created 5, closed 2"
    assert ranking.sweep(tmp_path,reg,panes,snapshot=lambda:([rows[1]],rows),
                         counts_reader=counts,push=push,log=logs.append)==['fleet']
    assert ranking.sweep(tmp_path,reg,panes,snapshot=lambda:([rows[1]],rows),
                         counts_reader=counts,push=push,log=logs.append)==[]
    assert len(sent)==1 and sent[0][0]=='chief'
    assert 'worker: active P2 below unowned READY urgent' in sent[0][1]
    assert 'created 5, closed 2' in sent[0][1]
    assert 'unowned P0: urgent' in logs[0] and repr(rows)==before


def test_unknown_snapshot_cannot_send_or_claim_no_unowned_work(tmp_path):
    logs=[]
    def fail():raise OSError('unreadable')
    assert ranking.sweep(tmp_path,None,None,snapshot=fail,log=logs.append)==[]
    assert 'UNKNOWN' in logs[0] and 'none' not in logs[0]
