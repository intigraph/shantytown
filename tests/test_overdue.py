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
    calls=[]; wire=[dict(subject="https://seeds.local/item/a-1",graph="https://example.org/board",id="a-1",title="work",status="open",due={"datatype":"http://www.w3.org/2001/XMLSchema#dateTime","value":"2026-10-01T00:00:00Z"},assignee="https://seeds.local/principal/worker")]
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


def test_due_projection_validates_subject_before_grouping(monkeypatch):
    """Run the actual SELECT against RDF, including an identical-ID foreign row."""
    import pytest
    from rdflib import Dataset, URIRef, Literal, RDF
    from shantytown import seeds_plate as plate

    proof = SimpleNamespace(graph="urn:fixture:board")
    data = Dataset()
    graph = data.graph(URIRef(proof.graph))

    def add(subject):
        subject = URIRef(subject)
        graph.add((subject, RDF.type, URIRef(plate.SCHEMA + "Action")))
        for predicate, value in (
            (plate.SCHEMA + "identifier", "example-1"),
            (plate.SCHEMA + "name", "work"),
            (plate.SEEDS + "ontology/status", "open"),
            ("http://www.w3.org/2002/12/cal/ical#due", "2026-10-01T00:00:00Z"),
        ):
            graph.add((subject, URIRef(predicate), Literal(value)))

    calls = []

    def query(_proof, text, timeout):
        calls.append(text)
        return {"rows": [{str(k): str(v) for k, v in row.asdict().items()}
                         for row in data.query(text)]}

    monkeypatch.setattr(plate, "_query", query)
    try:
        add(plate.SEEDS + "item/example-1")
        assert due_rows(proof).exact()[0]["id"] == "example-1"
        add("urn:foreign:example-1")
        assert not due_rows(proof).complete  # cannot collapse into canonical row
        graph.remove((URIRef(plate.SEEDS + "item/example-1"), None, None))
        assert not due_rows(proof).complete  # foreign subject alone is not absence
        assert len(calls) == 3 and all("LIMIT 2000" in text for text in calls)
    finally:
        data.close()


def test_no_card_owner_notice_goes_to_admin_without_mutating_item(tmp_path):
    rows=[dict(row("a-unknown"),assignee="missing"),row("a-known")]
    before=json.loads(json.dumps(rows)); sent=[]; logs=[]
    a=OverdueAlerter(tmp_path,Registry(),
        read=lambda:Answer.complete_read(rows,how="owner routing fixture"),
        deliver=lambda *args:sent.append(args) or True,
        now=lambda:datetime(2026,10,2,tzinfo=timezone.utc),log=logs.append)
    assert a.sweep()==["admin","worker"]
    assert a.sweep()==[]
    assert len(sent)==2 and {s[0] for s in sent}=={"admin","worker"}
    assert rows==before
    assert any("a-unknown owner missing has no card; notice to admin" in line for line in logs)


def test_no_card_owner_without_admin_is_unknown_and_known_owner_proceeds(tmp_path):
    class NoAdmin(Registry):
        def all(self): return Answer.complete_read([],how="no administrator fixture")
    sent=[]; logs=[]
    a=OverdueAlerter(tmp_path,NoAdmin(),
        read=lambda:Answer.complete_read([dict(row("a-missing"),assignee="missing"),row()],how="owner routing fixture"),
        deliver=lambda *args:sent.append(args) or True,
        now=lambda:datetime(2026,10,2,tzinfo=timezone.utc),log=logs.append)
    assert a.sweep()==["worker"]
    assert a.sweep()==[] and len(sent)==1
    assert any("administrator UNKNOWN" in line for line in logs)


def test_unknown_unlock_owner_is_not_rerouted(tmp_path):
    sent=[]
    a=OverdueAlerter(tmp_path,Registry(),
        read=lambda:Answer.complete_read([],how="fixture due"),
        events=lambda:Answer.complete_read([dict(id="a-unlock",kind="unlock",episode="event-1",recipient="missing")],how="fixture unlock"),
        deliver=lambda *args:sent.append(args) or True)
    assert a.sweep()==[] and not sent


def test_scheduled_delivery_callback_retains_known_receipt():
    """Exercise the actual nested callback without a fleet run or real sender."""
    import ast
    import inspect
    from shantytown import cli
    from shantytown.overdue import PendingReceipt

    source = ast.parse(inspect.getsource(cli))
    callback = next(node for node in ast.walk(source)
                    if isinstance(node, ast.FunctionDef) and node.name == "deliver_due")
    sent = []
    expected = object()
    def sender(target, card, body, panes, **kwargs):
        sent.append((target.agent, body))
        print("delivered to inbox as inbox-receipt-1")
        return cli.OK
    namespace = dict(vars(cli), a=SimpleNamespace(agent="original"), panes=None,
                     _registry=lambda _: Registry(), _inbox_durable=sender,
                     verify_due_receipt=lambda *args: expected,
                     PendingReceipt=PendingReceipt)
    exec(compile(ast.Module(body=[callback], type_ignores=[]), cli.__file__, "exec"), namespace)
    assert namespace["deliver_due"]("worker", "[marker]", "body") is expected
    assert sent == [("worker", "[marker] body")]

    def unknown(*args):
        raise RuntimeError("read unavailable after committed delivery")
    namespace["verify_due_receipt"] = unknown
    pending = namespace["deliver_due"]("worker", "[second]", "body")
    assert isinstance(pending, PendingReceipt)
    assert pending.identifier == "inbox-receipt-1"
