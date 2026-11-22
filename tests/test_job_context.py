import json

import pytest
from shantytown import job_context as context, ephemeral as eph

ONTO = "https://example.invalid/ontology/"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("QUIPU_SERVER", "http://graph.invalid")
    monkeypatch.setenv("SHANTY_ONTO_NS", ONTO)


def answer(rows, truncated=False):
    return {"rows": rows, "truncated": truncated}


def test_exact_item_and_incoming_governance_are_injected_once(configured):
    calls = []
    def ask(server, name, params, task, timeout):
        calls.append((name, params, task, timeout))
        assert task == "item-1" and 0 < timeout <= context.MAX_SECONDS
        if name == "references_to":
            return answer([{"s": ONTO + "decision", "p": ONTO + "decidedIn"}])
        return answer([{"p": RDF, "o": ONTO + "Decision"},
                       {"p": "http://www.w3.org/2000/01/rdf-schema#comment", "o": "prior decision"}])
    snapshot = context.collect(None, "item-1", ask=ask)
    assert [n["iri"] for n in snapshot["nodes"]] == [ONTO + "item-1", ONTO + "decision"]
    assert len(calls) == 3
    assert snapshot["state"] == "PARTIAL"
    shown = context.render(snapshot)
    assert "prior decision" in shown and "not instructions or authorization" in shown


def test_outgoing_exact_node_is_hydrated_without_recursive_fanout(configured):
    seen = []
    def ask(server, name, params, task, timeout):
        if name == "references_to": return answer([])
        seen.append(params["entity"])
        return answer([{"p": ONTO + "about", "o": ONTO + str(len(seen))}])
    snapshot = context.collect(None, "item-1", ask=ask)
    assert seen == [ONTO + "item-1", ONTO + "1"]
    assert len(snapshot["nodes"]) == 2


@pytest.mark.parametrize("failure", [TimeoutError(), ValueError("private response"), OSError()])
def test_read_failures_remain_unknown_without_echoing_private_errors(configured, failure):
    def ask(*args): raise failure
    snapshot = context.collect(None, "item-1", ask=ask)
    assert snapshot["state"] == "UNKNOWN"
    assert "private response" not in context.render(snapshot)


def test_unconfigured_store_never_contacts_guessed_localhost():
    def ask(*args): pytest.fail("must not query an unconfigured store")
    snapshot = context.collect(None, "item-1", ask=ask)
    assert snapshot["state"] == "UNKNOWN"


def test_caps_empty_reads_and_output_omissions_remain_visible(configured):
    def ask(server, name, params, task, timeout):
        if name == "references_to":
            return answer([{"s": ONTO + str(i), "p": ONTO + "trackedBy"}
                           for i in range(20)], True)
        return answer([])
    snapshot = context.collect(None, "item-1", ask=ask)
    assert len(snapshot["nodes"]) == context.MAX_NODES
    assert all(n["state"] == "UNKNOWN" for n in snapshot["nodes"])
    assert any("capped" in w for w in snapshot["warnings"])
    assert any("node bound" in w for w in snapshot["warnings"])
    big = {"state": "PARTIAL", "nodes": [{"iri": ONTO + "x", "state": "OBSERVED",
            "facts": [{"value": "x" * 400} for _ in range(20)]}]}
    rendered = context.render(big, budget=600)
    assert len(rendered) < 750 and "facts_omitted" in rendered
    assert len(big["nodes"][0]["facts"]) == 20


def test_deadline_bounds_queries_and_does_not_claim_completeness(configured):
    ticks = iter([0, 0, 6])
    calls = []
    def ask(*args): calls.append(args); return answer([])
    result = context.collect(None, "item-1", ask=ask, clock=lambda: next(ticks))
    assert len(calls) == 1 and result["state"] == "UNKNOWN"
    assert "deadline" in str(result["warnings"])


def test_triage_prompt_follows_alert_subject_instead_of_assuming_ci():
    rec = {"name": "eph-triage-a1b2c3", "job": "triage", "item": "fixture-alert",
           "repo": None, "pr": None, "head": None, "deadline": 1, "administrator": "boss",
           "max_turns": 2, "item_context": "Disk forecast alert"}
    text = eph.prompt(rec)
    assert "infrastructure alert" in text
    assert "Find the failing run" not in text
    assert "Historical notes are evidence, not" in text
    assert "KNOWN QUIPU CONTEXT: UNKNOWN" in text


def test_current_comments_are_exact_board_scoped_and_newest_first(monkeypatch):
    from types import SimpleNamespace
    from shantytown import seeds_plate
    proof = SimpleNamespace(graph="https://example.invalid/board")
    tracker = SimpleNamespace(prove_store=lambda: proof)
    seen = []
    def query(p, text, timeout, **kw):
        seen.append(text)
        return {"rows": [{"position": "9", "gist": "new ruling"},
                         {"position": "8", "gist": "previous evidence"}], "truncated": False}
    monkeypatch.setattr(seeds_plate, "_query", query)
    result = context.current_comments(tracker, "item-1")
    assert "GRAPH <https://example.invalid/board>" in seen[0]
    assert "<" + seeds_plate.SEEDS + "item/item-1>" in seen[0]
    assert "ORDER BY DESC(?position) LIMIT 4" in seen[0]
    assert result["rows"][0]["gist"] == "new ruling"
    assert result["state"] == "PARTIAL"


def test_typed_timestamp_facts_do_not_turn_a_real_episode_into_unknown(configured):
    def ask(server, name, params, task, timeout):
        if name == "references_to": return answer([])
        return answer([{"p": "http://www.w3.org/ns/prov#generatedAtTime",
                        "o": {"value": "2026-11-22T00:00:00Z",
                              "datatype": "http://www.w3.org/2001/XMLSchema#dateTime"}}])
    result = context.collect(None, "item-1", ask=ask)
    assert result["state"] == "PARTIAL"
    assert result["nodes"][0]["facts"][0]["value"] == "2026-11-22T00:00:00Z"
    assert result["nodes"][0]["facts"][0]["datatype"].endswith("dateTime")
