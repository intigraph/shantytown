"""The graph orders a labelled scope; it never gains dispatch or page custody."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from shantytown import backlog_rank_report as report
from shantytown import ranking_check
from shantytown.answer import Answer
from shantytown.protocols import Agent
from shantytown.sd import StoreProof

NOW = datetime(2026, 11, 8, 11, tzinfo=timezone.utc)
PROOF = StoreProof("--quipu", None, "https://example.test", "test", "urn:test:board")


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(report, "deployment_default", lambda root, key: "1")
    monkeypatch.setattr(report, "resolve_server", lambda **kw: PROOF.quipu_url)


def item(ident, **fields):
    return dict(id=ident, title="ordinary work", status="open", priority=1,
                assignee=None, labels=[], created_at="2026-11-01T00:00:00Z") | fields


def reader_for(candidates, calls, transform=lambda rows: rows):
    def reader(root, name, params, **bounds):
        calls.append((name, params, bounds))
        assert name == "seeds_work_rank_v2" and params["owner"] == ""
        assert params["board"] == PROOF.graph and bounds == dict(limit=65, timeout=2)
        # Intentionally DIFFERENT from the local candidate order.
        rows = [dict(r, revision=7, sampled_at=params["now"],
                     deferral_observation="UNKNOWN") for r in reversed(candidates)]
        return transform(rows)
    return reader


def test_flag_off_does_no_store_query_ledger_or_log_io(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "deployment_default", lambda *a: None)
    def forbidden(*a, **kw):
        pytest.fail("OFF must not reach this")
    report.sweep(tmp_path, [item("a")], forbidden, log=forbidden, reader=forbidden)
    assert list(tmp_path.iterdir()) == []


def test_empty_scope_is_not_a_store_or_network_probe(tmp_path):
    def forbidden(*a, **kw):
        pytest.fail("no eligible IDs must not resolve or query a store")
    logs = []
    report.sweep(tmp_path, [], forbidden, reader=forbidden, log=logs.append, now=NOW)
    assert len(logs) == 1 and "0 eligible ordinary unowned READY" in logs[0]


def test_actual_sweep_consumes_graph_order_without_mutation_or_global_claim(tmp_path):
    candidates = [item("a"), item("b")]
    before = deepcopy(candidates)
    calls, logs = [], []
    report.sweep(tmp_path, candidates, lambda: PROOF, now=NOW, log=logs.append,
                 reader=reader_for(candidates, calls))
    assert len(calls) == 1 and len(logs) == 1
    assert "2/2" in logs[0] and "b P1, a P1" in logs[0]
    assert "complete supplied READY scope" in logs[0]
    assert "no dispatch/admission or global-order claim" in logs[0]
    assert candidates == before and "revision" not in candidates[0]
    assert json.loads((tmp_path / "notify" / report.LEDGER).read_text()) == {"at": NOW.timestamp()}


@pytest.mark.parametrize("fields", [
    {"assignee": "another"}, {"status": "in_progress"}, {"status": "deferred"},
    {"labels": ["blocked:external"]}, {"labels": ["needs-stiwi"]},
    {"title": "ASK Stiwi: retained decision"}, {"labels": ["desk"]},
    {"defer_until": "2026-12-01T00:00:00Z"},
    {"labels": ["deploy-operation"]}, {"agent_context": "unreadable"},
    {"agent_context": '{"deploy_admission":{"phase":"PLANNED"}}'},
    {"title": "inbox: retained pointer"}, {"blocked_count": 1},
])
def test_protected_or_nonready_rows_never_enter_query_scope(fields):
    selected, total = report.scope([item("ordinary"), item("protected", **fields)], now=NOW)
    assert [r["id"] for r in selected] == ["ordinary"] and total == 1


def test_cap_is_scoped_and_disclosed_without_extra_queries(tmp_path):
    rows = [item(f"w{i:03}") for i in range(70)]
    selected, total = report.scope(list(reversed(rows)))
    assert len(selected) == 64 and total == 70 and selected[0]["id"] == "w000"
    calls, logs = [], []
    report.sweep(tmp_path, rows, lambda: PROOF, now=NOW, log=logs.append,
                 reader=reader_for(selected, calls))
    assert len(calls) == 1 and len([k for k in calls[0][1] if k.startswith("id")]) == 64
    assert "64/70" in logs[0] and "remaining IDs not ranked" in logs[0]


def test_defer_clock_must_be_proven_and_elapsed_before_scope_inclusion():
    with pytest.raises(ValueError, match="defer clock"):
        report.scope([item("ambiguous", defer_until="unknown")], now=NOW)
    rows, total = report.scope([item("elapsed", defer_until="2026-11-07T00:00:00Z")], now=NOW)
    assert total == 1 and rows[0]["id"] == "elapsed"


@pytest.mark.parametrize("transform", [
    lambda rows: [], lambda rows: rows + rows, lambda rows: [None],
    lambda rows: [dict(rows[0], id="foreign")],
    lambda rows: [dict(rows[0], revision=True)],
    lambda rows: [dict(rows[0], revision=0)],
    lambda rows: [dict(rows[0], priority=True)],
    lambda rows: [dict(rows[0], sampled_at="old")],
    lambda rows: [dict(rows[0], assignee="other")],
    lambda rows: [dict(rows[0], status="deferred")],
    lambda rows: [dict(rows[0], priority=0)],
    lambda rows: [dict(rows[0], created_at="2020-01-01T00:00:00Z")],
    lambda rows: [dict(rows[0], due_at="2026-11-09")],
])
def test_unknown_proof_has_no_fallback_order(transform, tmp_path):
    calls, logs, rows = [], [], [item("a")]
    with pytest.raises(ValueError):
        report.sweep(tmp_path, rows, lambda: PROOF, now=NOW, log=logs.append,
                     reader=reader_for(rows, calls, transform))
    assert len(calls) == 1 and logs == []


def test_failed_read_is_not_polled_and_never_recorded_as_success(tmp_path):
    calls = []
    def fail(*a, **kw):
        calls.append(1)
        raise PermissionError("fixture refusal")
    with pytest.raises(PermissionError):
        report.sweep(tmp_path, [item("a")], lambda: PROOF, now=NOW, reader=fail)
    report.sweep(tmp_path, [item("a")], lambda: PROOF,
                 now=NOW + timedelta(seconds=299), reader=fail)
    assert calls == [1]
    with pytest.raises(PermissionError):
        report.sweep(tmp_path, [item("a")], lambda: PROOF,
                     now=NOW + timedelta(seconds=300), reader=fail)
    assert calls == [1, 1]


@pytest.mark.parametrize("proof", [None, PROOF.__dict__,
    StoreProof("--quipu", None, "https://foreign.test", "test", PROOF.graph),
    StoreProof("--quipu", None, PROOF.quipu_url, "test", None)])
def test_wrong_or_unproven_store_refuses_before_query(proof, tmp_path):
    calls = []
    with pytest.raises(ValueError, match="identity"):
        report.sweep(tmp_path, [item("a")], lambda: proof, now=NOW,
                     reader=lambda *a, **kw: calls.append(1))
    assert calls == []


@pytest.mark.parametrize("previous", [[], {"at": True}, {"at": float("nan")},
                                      {"at": NOW.timestamp() + 1}, {"other": 1}])
def test_ambiguous_attempt_clock_does_not_trigger_a_read(previous, tmp_path):
    path = tmp_path / "notify" / report.LEDGER
    path.parent.mkdir()
    path.write_text(json.dumps(previous))
    calls = []
    with pytest.raises(ValueError, match="clock"):
        report.sweep(tmp_path, [item("a")], lambda: PROOF, now=NOW,
                     reader=lambda *a, **kw: calls.append(1))
    assert calls == []


@pytest.mark.parametrize("fault", ["query", "ledger"])
def test_actual_ranking_sweep_preserves_p0_page_and_retry_identity(tmp_path, monkeypatch, fault):
    monkeypatch.setattr(report, "resolve_server", lambda **kw: PROOF.quipu_url)
    cards = [Agent(name="chief", role="administrator", pane="chief")]
    reg = SimpleNamespace(all=lambda: Answer.complete_read(cards, how="fixture"))
    panes = SimpleNamespace(exists=lambda pane: True)
    ready = [item("urgent", priority=0)]
    logs, sent = [], []
    def fail(*a, **kw):
        raise PermissionError("fixture unavailable")
    monkeypatch.setattr(report, "ask", fail)
    if fault == "ledger":
        monkeypatch.setattr(report, "write_json_atomic", fail)
    args = dict(snapshot=lambda: (ready, ready), counts_reader=lambda root: "counts",
                rank_store=lambda: PROOF, log=logs.append,
                push=lambda *a: sent.append(a[-1]) or "chief")
    assert ranking_check.sweep(tmp_path, reg, panes, **args) == ["fleet"]
    assert ranking_check.sweep(tmp_path, reg, panes, **args) == []
    assert len(sent) == 1 and "urgent P0" in sent[0]
    assert "graph rank observation" not in sent[0]
    assert any("graph rank observation UNKNOWN" in line for line in logs)


def test_actual_cli_callback_reuses_the_selected_tracker_and_cached_store_proof(tmp_path, monkeypatch):
    import ast
    from shantytown import cli
    from shantytown.sd import SdTracker
    tree = ast.parse(Path(cli.__file__).read_text())
    function, = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == "_role_ranking_report"]
    tracker = SdTracker(quipu=PROOF.quipu_url, prefix="test")
    packet = ([item("a")], [item("a")])
    calls = []
    monkeypatch.setattr(tracker, "ranking_rows", lambda: packet)
    monkeypatch.setattr(tracker, "prove_store", lambda: calls.append("cached-proof") or PROOF)
    def capture(root, reg, panes, *, snapshot, rank_store, **kwargs):
        assert snapshot() == packet and calls == ["tracker"]
        assert rank_store() is PROOF
        assert calls == ["tracker", "cached-proof"]
        return ["captured"]
    monkeypatch.setattr(ranking_check, "sweep", capture)
    namespace = {"__name__": "shantytown.cli", "__package__": "shantytown",
                 "a": SimpleNamespace(root=tmp_path), "reg": None, "panes": None,
                 "_log": lambda text: None,
                 "_tracker": lambda args: calls.append("tracker") or tracker}
    # Execute the shipped nested callback itself; no tend, dispatch or live reader.
    exec(compile(ast.Module(body=[function], type_ignores=[]), "<actual-cli-ranking>", "exec"), namespace)
    assert namespace["_role_ranking_report"]() == ["captured"]


def test_shipped_query_matches_actual_lean_projection_on_native_rdf(tmp_path, monkeypatch):
    from rdflib import Dataset, Graph, Literal, Namespace, URIRef, RDF
    from rdflib.namespace import XSD
    from shantytown import seeds_plate
    q, schema = Namespace("https://quipu.dev/ontology/"), Namespace("https://schema.org/")
    seeds, ical = Namespace("https://seeds.local/ontology/"), Namespace("http://www.w3.org/2002/12/cal/ical#")
    source = Graph().parse(Path(__file__).parents[1] / "queries/seeds-work-rank-v2.ttl")
    template = str(source.value(URIRef("urn:quipu:query:seeds_work_rank_v2"), q.sparqlTemplate))
    data = Dataset()
    graph = data.graph(URIRef(PROOF.graph))
    rows = [item("old", created_at="2026-10-01T00:00:00Z"),
            item("due", due_at="2026-11-07T00:00:00Z")]
    for row in rows:
        subject = URIRef("https://seeds.local/item/" + row["id"])
        for predicate, value in [(RDF.type, schema.Action),
                (schema.name, Literal(row["title"])), (schema.identifier, Literal(row["id"])),
                (schema.version, Literal(3)), (seeds.priority, Literal(1)),
                (seeds.status, Literal("open")),
                (schema.dateCreated, Literal(row["created_at"], datatype=XSD.dateTime))]:
            graph.add((subject, predicate, value))
        if row.get("due_at"):
            graph.add((subject, ical.due, Literal(row["due_at"], datatype=XSD.dateTime)))
    def native_rows(query):
        # HTTP serializes date terms as lexical strings, not Python datetimes.
        # Both production readers observe these SAME stored lexical values.
        return [{str(k): str(v) if v.datatype == XSD.dateTime else v.toPython()
                 for k, v in row.asdict().items()} for row in data.query(query)]
    monkeypatch.setattr(seeds_plate, "_query", lambda proof, query, timeout: {
        "rows": native_rows(query), "truncated": False})
    actual_snapshot = seeds_plate.ranking_rows(PROOF).exact()
    assert len(actual_snapshot) == 2 and all("revision" not in r for r in actual_snapshot)
    def reader(root, name, params, **bounds):
        rendered = template
        for key, value in ({f"id{i:02}": "" for i in range(64)} | params).items():
            rendered = rendered.replace("{" + key + "}", value)
        return native_rows(rendered)
    logs = []
    report.sweep(tmp_path, actual_snapshot, lambda: PROOF, now=NOW, log=logs.append, reader=reader)
    assert "due P1, old P1" in logs[0]


@pytest.mark.parametrize("metadata", [
    {},
    {"deferral_observation": "OBSERVED"},
    {"deferral_observation": "UNKNOWN", "observed_deferral_writes": 1},
    {"deferral_observation": "OBSERVED", "observed_deferral_writes": True,
     "deferral_observed_since": "2026-11-01T00:00:00Z"},
    {"deferral_observation": "OBSERVED", "observed_deferral_writes": 0,
     "deferral_observed_since": "2026-11-01T00:00:00Z"},
    {"deferral_observation": "OBSERVED", "observed_deferral_writes": 9223372036854775808,
     "deferral_observed_since": "2026-11-01T00:00:00Z"},
    {"deferral_observation": "OBSERVED", "observed_deferral_writes": 1,
     "deferral_observed_since": "unreadable"},
    {"deferral_observation": "OBSERVED", "observed_deferral_writes": 1,
     "deferral_observed_since": "2027-01-01T00:00:00Z"},
])
def test_v2_deferral_metadata_refuses_incomplete_or_invalid_observation(metadata, tmp_path):
    candidates, calls, logs = [item("a")], [], []
    def replace_metadata(rows):
        row = rows[0]
        for key in ("deferral_observation", "observed_deferral_writes", "deferral_observed_since"):
            row.pop(key, None)
        row.update(metadata)
        return rows
    with pytest.raises(ValueError):
        report.sweep(tmp_path, candidates, lambda: PROOF, now=NOW, log=logs.append,
                     reader=reader_for(candidates, calls, replace_metadata))
    assert len(calls) == 1 and logs == []


def test_v2_observed_lower_bound_retains_the_same_read_only_report(tmp_path):
    candidates, calls, logs = [item("a")], [], []
    before = deepcopy(candidates)
    def observed(rows):
        rows[0].update(deferral_observation="OBSERVED", observed_deferral_writes=4,
                       deferral_observed_since="2026-11-01T00:00:00Z")
        return rows
    report.sweep(tmp_path, candidates, lambda: PROOF, now=NOW, log=logs.append,
                 reader=reader_for(candidates, calls, observed))
    assert len(calls) == 1 and len(logs) == 1 and candidates == before
    assert "no dispatch/admission or global-order claim" in logs[0]
