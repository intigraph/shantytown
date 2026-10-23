"""Independent contract stub: no Quipu implementation, writes or live service."""
from copy import deepcopy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
from urllib.error import HTTPError

import pytest

from shantytown.answer import Answer, PartialAnswer
from shantytown.sd import StoreProof
from shantytown import seeds_inbox as exact
from shantytown import seeds_inbox_projection as projection

G = "https://example.test/project/inbox"
PROOF = StoreProof("fixture", None, "https://example.test", "demo", G)
PREDICATES = {
    "identifier": "https://schema.org/identifier",
    "title": "https://schema.org/name",
    "status": "https://seeds.local/ontology/status",
    "priority": "https://seeds.local/ontology/priority",
    "created": "https://schema.org/dateCreated",
    "kind": "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
}
CAPABILITIES = {"actions": ["aggregate", "list", "rows"], "declared": [{
    "name": "inbox", "key": "https://schema.org/agent",
    "columns": [{"name": name, "predicate": p} for name, p in PREDICATES.items()]}, {"name": "inbox_legacy",
    "key": "https://seeds.local/ontology/revision", "columns": []}]}


def row(ident="demo-001", owner="worker", *, graph=G, status="open", title="inbox: marker"):
    columns = {"identifier": ident, "title": title, "status": status,
               "priority": 1, "created": "2026-10-23T00:00:00Z",
               "kind": {"iri": "https://schema.org/Action"}}
    return {"entity": "https://seeds.local/item/" + ident, "graph": graph,
            "key": owner, "key_plain": isinstance(owner, str), "multi": False,
            "columns": columns, "plain": {k: isinstance(v, str) for k, v in columns.items()}}


class Stub:
    """Faithful grouped proofs and bounded rows; all responses carry a tx."""
    def __init__(self, rows=(), *, capabilities=None, tx=713621, legacy_total=0):
        self.rows = list(rows)
        self.capabilities = deepcopy(CAPABILITIES if capabilities is None else capabilities)
        self.tx, self.calls, self.legacy_total = tx, [], legacy_total

    def __call__(self, proof, payload, timeout):
        self.calls.append(deepcopy(payload))
        assert timeout > 0
        if payload == {"action": "list"}:
            return deepcopy(self.capabilities)
        assert payload["graphs"] == [proof.graph, proof.graph + "#seeds-ephemeral"]
        if payload["name"] == "inbox_legacy":
            assert payload["action"] == "aggregate" and "key_in" not in payload
            return {"total": self.legacy_total, "groups": [], "truncated": False,
                    "tx": self.tx, "multi_valued_rows": 0}
        assert payload["name"] == "inbox"
        selected = [r for r in self.rows if r["graph"] in payload["graphs"]
                    and r["key"] in payload["key_in"]]
        for column, wanted in payload.get("where", {}).items():
            selected = [r for r in selected if r["columns"][column] in wanted]
        if payload["action"] == "aggregate":
            column = payload["group_by"]
            groups = {}
            for r in selected:
                value = r["columns"][column]
                key = (r["graph"], json.dumps(value, sort_keys=True))
                group = groups.setdefault(key, {"graph": r["graph"], "value": value,
                                                "plain": r["plain"][column], "n": 0})
                group["n"] += 1
            return {"total": len(selected), "groups": list(groups.values()), "truncated": False,
                    "tx": self.tx, "multi_valued_rows": sum(r["multi"] for r in selected)}
        assert payload["action"] == "rows"
        assert set(payload["columns"]) == set(PREDICATES)
        assert set(payload) == {"action", "name", "graphs", "key_in", "where", "columns", "limit"}
        assert 1 <= payload["limit"] <= 1000
        selected.sort(key=lambda r: r["entity"])
        limited = selected[:payload["limit"]]
        return {"rows": deepcopy(limited), "tx": self.tx,
                "truncated": len(selected) > len(limited),
                "multi_valued_rows": sum(r["multi"] for r in limited)}


def test_complete_snapshot_preserves_scope_aliases_and_watermark():
    records = [row(), row("demo-002", "crew/worker", graph=G + "#seeds-ephemeral"),
               row("demo-003", {"iri": "https://seeds.local/principal/worker"}),
               row("demo-004", status="closed"), row("demo-005", title="ordinary work"),
               row("demo-006", owner="foreign")]
    stub = Stub(records)
    result = projection.read(PROOF, "crew/worker", post=stub)
    assert {r["id"] for r in result.answer.exact()} == {"demo-001", "demo-002", "demo-003"}
    assert result.tx == 713621 and "tx=713621" in result.answer.how
    assert len(stub.calls) == 5 and "key_in" in stub.calls[-1]
    assert {r["id"] for r in projection.read(PROOF, "crew/worker", include_closed=True,
                                             post=stub).answer.exact()} == {
        "demo-001", "demo-002", "demo-003", "demo-004"}


@pytest.mark.parametrize("owner,count", [("recipient-a", 15), ("recipient-b", 231), ("recipient-c", 151)])
def test_three_owner_exact_id_oracle(owner, count):
    # The independent golden set is fixed before constructing transport rows.
    golden = {f"fixture-{owner}-{i:04}" for i in range(count)}
    records = [row(ident, owner, graph=G if i % 2 else G + "#seeds-ephemeral")
               for i, ident in enumerate(sorted(golden))]
    records += [row("fixture-closed", owner, status="closed"),
                row("fixture-work", owner, title="ordinary work"),
                row("fixture-foreign", "someone-else")]
    observed = projection.read(PROOF, owner, post=Stub(records))
    assert {r["id"] for r in observed.answer.exact()} == golden
    assert observed.tx == 713621


@pytest.mark.parametrize("slot", [0, 1, 2])
def test_private_archived_exact_id_oracle(slot):
    path = os.environ.get("PYTEST_INBOX_ORACLE_FIXTURE")
    if not path:
        pytest.skip("private exact-ID archive supplied only for the owner evidence run")
    owners = json.loads(Path(path).read_text())["owners"]
    owner = sorted(owners)[slot]
    fixture = owners[owner]
    records = []
    for record in fixture["records"]:
        r = row(record["id"], record["assignee"], status=record["status"], title=record["title"])
        r["columns"].update(priority=record["priority"], created=record.get("created_at"))
        records.append(r)
    answer = projection.read(PROOF, owner, post=Stub(records)).answer
    ids = sorted(r["id"] for r in answer.exact())
    assert len(ids) == fixture["count"]
    assert hashlib.sha256(json.dumps(ids).encode()).hexdigest() == fixture["ids_sha256"]


@pytest.mark.parametrize("cap", [{}, {"actions": ["list", "aggregate"]}])
def test_unsupported_server_uses_exact_whole_request(monkeypatch, cap):
    calls = []
    expected = Answer.complete_read([{"id": "proved"}], how="exact stub")
    monkeypatch.setattr(exact, "read", lambda *a, **kw: calls.append(kw) or expected)
    result = projection.read(PROOF, "worker", include_closed=True, post=Stub(capabilities=cap))
    assert result.answer is expected and result.tx is None
    assert len(calls) == 1 and calls[0]["include_closed"] is True


@pytest.mark.parametrize("variant", ["multi", "shadow", "legacy"])
def test_ambiguity_never_uses_partial_projection(monkeypatch, variant):
    records = [row()]
    if variant == "multi":
        records[0]["multi"] = True
    elif variant == "shadow":
        records.append(row(graph=G + "#seeds-ephemeral"))
    else:
        pass  # A standalone legacy subject is outside the owner rows.
    calls = []
    refused = Answer.capped([], how="exact refusal control", caveat="unverified")
    monkeypatch.setattr(exact, "read", lambda *a, **kw: calls.append(1) or refused)
    result = projection.read(PROOF, "worker", post=Stub(records, legacy_total=int(variant == "legacy")))
    assert result.answer is refused and result.tx is None and calls == [1]


@pytest.mark.parametrize("bad", [None, "alien", {"iri": "https://example.test/open"}])
def test_ordinary_owned_bad_status_cannot_be_hidden(monkeypatch, bad):
    records = [row(), row("demo-work", title="ordinary work", status=bad)]
    monkeypatch.setattr(exact, "read", lambda *a, **kw:
                        Answer.capped([], how="exact negative", caveat="bad owned status"))
    result = projection.read(PROOF, "worker", post=Stub(records))
    assert not result.answer.complete and result.tx is None


@pytest.mark.parametrize("field,value", [("identifier", "wrong"), ("identifier", None),
                                         ("title", None), ("priority", True), ("priority", 5)])
def test_invalid_selected_fields_refuse(field, value):
    r = row()
    r["columns"][field] = value
    r["plain"][field] = isinstance(value, str)
    answer = projection.read(PROOF, "worker", post=Stub([r])).answer
    # Absent title is not a message, matching the exact selector's behaviour.
    if field == "title":
        assert answer.exact() == []
    else:
        assert not answer.complete


def test_truncation_errors_without_serial_hydration(monkeypatch):
    monkeypatch.setattr(exact, "read", lambda *a, **kw: pytest.fail("truncation is not fallback"))
    stub = Stub(row(f"fixture-{i:04}") for i in range(1001))
    result = projection.read(PROOF, "worker", post=stub)
    assert not result.answer.complete and len(stub.calls) == 5
    with pytest.raises(PartialAnswer):
        result.answer.exact()


@pytest.mark.parametrize("mutation", ["missing_tx", "bool_tx", "truncated", "bad_columns",
                                     "foreign_graph", "foreign_owner", "duplicate", "order",
                                     "missing_multi", "bad_type"])
def test_wire_failures_are_incomplete_without_fallback(monkeypatch, mutation):
    stub = Stub([row(), row("demo-002")])
    monkeypatch.setattr(exact, "read", lambda *a, **kw: pytest.fail("wire failure fallback"))
    def post(proof, payload, timeout):
        data = stub(proof, payload, timeout)
        if payload["action"] != "rows":
            return data
        if mutation == "missing_tx":
            data.pop("tx")
        elif mutation == "bool_tx":
            data["tx"] = True
        elif mutation == "truncated":
            data["truncated"] = True
        elif mutation == "bad_columns":
            data["rows"][0]["columns"].pop("identifier")
        elif mutation == "foreign_graph":
            data["rows"][0]["graph"] = "https://example.test/foreign"
        elif mutation == "foreign_owner":
            data["rows"][0]["key"] = "other"
        elif mutation == "duplicate":
            data["rows"].insert(0, deepcopy(data["rows"][0]))
        elif mutation == "order":
            data["rows"].reverse()
        elif mutation == "missing_multi":
            data["rows"][0].pop("multi")
        else:
            data["rows"][0]["columns"]["kind"] = {"unsupported": "value"}
        return data
    result = projection.read(PROOF, "worker", post=post)
    assert not result.answer.complete and result.tx is None


def test_timeout_and_malformed_advertisement_are_not_unsupported(monkeypatch):
    monkeypatch.setattr(exact, "read", lambda *a, **kw: pytest.fail("unknown capability fallback"))
    def unavailable(*args):
        raise TimeoutError("synthetic private detail")
    assert not projection.read(PROOF, "worker", post=unavailable).answer.complete
    answer = projection.read(PROOF, "worker", post=Stub(capabilities={"actions": "rows"})).answer
    assert not answer.complete and "private" not in answer.caveat


def test_missing_declaration_evidence_refuses():
    cap = deepcopy(CAPABILITIES)
    cap["declared"][0]["columns"].pop()
    assert not projection.read(PROOF, "worker", post=Stub(capabilities=cap)).answer.complete


def test_positive_empty_is_fresh_and_complete():
    stub = Stub()
    first = projection.read(PROOF, "worker", post=stub)
    assert first.answer.exact() == [] and first.tx == 713621
    stub.tx += 1
    stub.rows.append(row())
    second = projection.read(PROOF, "worker", post=stub)
    assert len(second.answer.exact()) == 1 and second.tx == 713622
    assert len(stub.calls) == 10


def test_large_closed_history_never_crosses_rows_limit():
    golden = {f"fixture-live-{i:04}" for i in range(231)}
    stub = Stub([row(ident) for ident in golden] +
                [row(f"fixture-closed-{i:04}", status="closed") for i in range(6500)])
    result = projection.read(PROOF, "worker", post=stub)
    assert {r["id"] for r in result.answer.exact()} == golden
    assert len(stub.calls) == 5 and stub.calls[-1]["limit"] == 1000


def test_changed_tx_retries_all_proofs_once():
    stub = Stub([row()])
    changes = []
    def post(proof, payload, timeout):
        if payload["action"] == "rows" and not changes:
            stub.tx += 1
            changes.append(1)
        return stub(proof, payload, timeout)
    result = projection.read(PROOF, "worker", post=post)
    assert result.tx == 713622 and len(result.answer.exact()) == 1
    assert len(stub.calls) == 9


def test_busy_store_falls_back_after_one_retry_not_a_loop(monkeypatch):
    stub = Stub([row()])
    calls = []
    expected = Answer.complete_read([], how="exact snapshot")
    monkeypatch.setattr(exact, "read", lambda *a, **kw: calls.append(1) or expected)
    def post(proof, payload, timeout):
        if payload["action"] == "rows":
            stub.tx += 1
        return stub(proof, payload, timeout)
    result = projection.read(PROOF, "worker", post=post)
    assert result.answer is expected and result.tx is None
    assert len(stub.calls) == 9 and calls == [1]


@pytest.mark.parametrize("mutation", ["sum", "graph", "duplicate", "missing_plain", "empty_rows"])
def test_proof_and_selection_completeness_controls(monkeypatch, mutation):
    stub = Stub([row()])
    monkeypatch.setattr(exact, "read", lambda *a, **kw: pytest.fail("malformed proof fallback"))
    def post(proof, payload, timeout):
        data = stub(proof, payload, timeout)
        if payload.get("group_by") == "status":
            if mutation == "sum":
                data["total"] += 1
            elif mutation == "graph":
                data["groups"][0]["graph"] = "https://example.test/foreign"
            elif mutation == "duplicate":
                data["groups"].append(deepcopy(data["groups"][0]))
            elif mutation == "missing_plain":
                data["groups"][0].pop("plain")
        if mutation == "empty_rows" and payload["action"] == "rows":
            data["rows"] = []
        return data
    assert not projection.read(PROOF, "worker", post=post).answer.complete


@pytest.mark.parametrize("field", ["identifier", "title"])
def test_typed_identity_does_not_become_a_plain_string(monkeypatch, field):
    r = row()
    r["plain"][field] = False
    calls = []
    refused = Answer.capped([], how="typed exact refusal", caveat="typed identity")
    monkeypatch.setattr(exact, "read", lambda *a, **kw: calls.append(1) or refused)
    result = projection.read(PROOF, "worker", post=Stub([r]))
    assert result.answer is refused and calls == [1]


def test_real_http_transport_uses_only_read_actions():
    stub = Stub([row()])
    errors = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            try:
                assert self.path == "/projections"
                assert self.headers["X-Quipu-Client"] == "seeds"
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                body = json.dumps(stub(PROOF, payload, 10)).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)
            except Exception as error:
                errors.append(type(error).__name__)
                self.send_error(500)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        proof = StoreProof("fixture", None, f"http://127.0.0.1:{server.server_port}", "demo", G)
        assert projection.read(proof, "worker").answer.exact()[0]["id"] == "demo-001"
        assert not errors
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert not thread.is_alive()


@pytest.mark.parametrize("code,fallback", [(404, True), (405, True), (403, False), (500, False)])
def test_list_http_failures_have_bounded_compatibility(monkeypatch, code, fallback):
    calls = []
    monkeypatch.setattr(exact, "read", lambda *a, **kw: calls.append(1) or
                        Answer.complete_read([], how="older server"))
    def failed(*args):
        raise HTTPError(PROOF.quipu_url, code, "synthetic", None, None)
    answer = projection.read(PROOF, "worker", post=failed).answer
    assert answer.complete is fallback and bool(calls) is fallback
