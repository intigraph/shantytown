from datetime import datetime, timezone
from types import SimpleNamespace
import json

import pytest
from shantytown.answer import Answer
from shantytown.overdue import OverdueAlerter
from shantytown.spec_reader import SpecReader
from shantytown.spec_boundary import consume

NOW = datetime(2026,10,15,tzinfo=timezone.utc)


class Registry:
    def all(self):
        return Answer.complete_read([SimpleNamespace(name="admin",role="administrator")],how="fixture")
    def get(self, who):
        if who not in ("owner","admin"):
            raise ValueError("unknown owner")
        return SimpleNamespace(name=who)


def event(urgent=False):
    return {"kind":"spec","id":"work-spec","episode":"2","version":2,"previous":1,
            "recipient":"owner","summary":"consolidated requirement","urgent":urgent}


def test_shared_digest_spec_once_and_unknown_ack_readback(tmp_path):
    sent=[]; ack_writes=[]; receipt=[None]
    def command(*args):
        if args[0] == "spec-receipt":
            return {"event":{"id":"work-spec","version":2,"receipt":receipt[0]}}
        if args[0] == "spec-receipt-ack":
            ack_writes.append(args); receipt[0]=args[-1]
            raise EOFError("ACK committed, response lost")
        raise AssertionError(args)
    producer=SpecReader(SimpleNamespace(_spec_json=command))
    def deliver(who,marker,body,*,urgent):
        sent.append((who,marker,body,urgent))
        return "inbox-receipt"
    reminder=OverdueAlerter(tmp_path,Registry(),read=lambda:Answer.complete_read([],how="fixture"),
        deliver=lambda *a:pytest.fail("must use boundary adapter"),specs=lambda:Answer.complete_read([event()],how="fixture"),
        spec_ack=producer.ack,spec_deliver=deliver,now=lambda:NOW)
    assert reminder.sweep()==["owner"]
    assert len(sent)==1 and not sent[0][-1]
    assert "work-spec spec v1 -> v2" in sent[0][2]
    assert "sd history" in sent[0][2] and len((sent[0][1]+sent[0][2]).encode())<400
    assert len(ack_writes)==1
    assert reminder.sweep()==[]
    assert len(sent)==len(ack_writes)==1
    state=json.loads(reminder.path.read_text())
    assert next(iter(state["entries"].values()))["ack"]=="confirmed"
    reminder.specs=lambda:Answer.complete_read([event(True)],how="fixture")
    assert reminder.sweep()==[]  # urgent flag is not a new generation


def test_missing_receipt_field_cannot_authorize_ack():
    calls=[]
    def command(*args):
        calls.append(args)
        return {"event":{"id":"work-spec","version":2}}
    with pytest.raises(ValueError,match="UNKNOWN"):
        SpecReader(SimpleNamespace(_spec_json=command)).ack("work-spec","2","receipt")
    assert len(calls)==1 and calls[0][0]=="spec-receipt"


def test_recipient_boundary_once_per_generation_owner_scope_unknown(tmp_path):
    rows=[{"id":"work-spec","title":"work","status":"open","priority":1,"assignee":"owner",
           "spec_version":2,"spec_previous_version":1,"spec_changed_at":"2026-10-14T23:00:00Z"}]
    read=lambda:Answer.complete_read(rows,how="scoped fixture")
    notice=consume(tmp_path,"owner",read,now=NOW)
    assert "SPEC CHANGED v1 -> v2 (unacked)" in notice
    assert consume(tmp_path,"owner",read,now=NOW) is None
    assert consume(tmp_path,"admin",read,now=NOW) is None
    rows[0].update(spec_version=3,spec_previous_version=2)
    assert "v2 -> v3" in consume(tmp_path,"owner",read,now=NOW)
    with pytest.raises(Exception):
        consume(tmp_path,"owner",lambda:Answer.capped([],how="UNKNOWN"),now=NOW)
    path=next((tmp_path/"notify").glob("*.json"));path.write_text("corrupt")
    with pytest.raises(Exception): consume(tmp_path,"owner",read,now=NOW)


def test_actual_rdf_spec_scope_keeps_deferred_out_of_dispatch(monkeypatch):
    from rdflib import Dataset, URIRef, Literal, RDF
    from shantytown import seeds_plate
    from shantytown.sd import StoreProof

    graph_name = "https://example.test/project/test"
    proof = StoreProof("--quipu", None, "https://example.test", "test", graph_name)
    data = Dataset()
    graph = data.graph(URIRef(graph_name))
    for identifier, owner, status, version in (
        ("test-ready", "owner", "open", None),
        ("test-changed", "owner", "deferred", 2),
        ("test-foreign", "another", "deferred", 2),
    ):
        subject = URIRef(seeds_plate.SEEDS + "item/" + identifier)
        graph.add((subject, RDF.type, URIRef(seeds_plate.SCHEMA + "Action")))
        values = {
            seeds_plate.SCHEMA + "identifier": identifier,
            seeds_plate.SCHEMA + "name": "controlled work",
            seeds_plate.SCHEMA + "agent": owner,
            seeds_plate.SEEDS + "ontology/status": status,
            seeds_plate.SEEDS + "ontology/priority": 1,
        }
        if version is not None:
            values[seeds_plate.SEEDS + "ontology/specVersion"] = version
        for predicate, value in values.items():
            graph.add((subject, URIRef(predicate), Literal(value)))

    def query(_proof, text, timeout):
        rows = [
            {str(key): value.toPython() if isinstance(value, Literal) else str(value)
             for key, value in result.asdict().items()}
            for result in data.query(text)
        ]
        return {"rows": rows, "count": len(rows), "truncated": False}

    monkeypatch.setattr(seeds_plate, "_query", query)
    monkeypatch.setattr(seeds_plate, "owner_shape_supported", lambda *a, **k: True)
    try:
        ordinary = seeds_plate.owner_rows(proof, "owner", decision=True)
        assert ordinary.complete
        assert {row["id"] for row in ordinary.exact()} == {"test-ready"}
        specs = seeds_plate.owner_rows(
            proof, "owner", decision=True, include_deferred=True, only_specs=True)
        assert specs.complete
        assert {row["id"] for row in specs.exact()} == {"test-changed"}
        assert specs.exact()[0]["status"] == "deferred"
        # A non-spec row with an invalid owner status must still poison the
        # shared guard; the new candidate filter cannot hide that evidence.
        invalid = URIRef(seeds_plate.SEEDS + "item/test-invalid")
        graph.add((invalid, RDF.type, URIRef(seeds_plate.SCHEMA + "Action")))
        graph.add((invalid, URIRef(seeds_plate.SCHEMA + "agent"), Literal("owner")))
        graph.add((invalid, URIRef(seeds_plate.SEEDS + "ontology/status"), Literal("unrecognized")))
        refused = seeds_plate.owner_rows(
            proof, "owner", decision=True, include_deferred=True, only_specs=True)
        assert not refused.complete
    finally:
        data.close()
