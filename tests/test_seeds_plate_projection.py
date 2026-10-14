"""Wire projection preserves plate semantics without hydrating issue bodies."""

import json

import pytest
from shantytown import br, seeds_plate
from shantytown.sd import SdTracker, StoreProof

G = "https://example.test/project/test"
PROOF = StoreProof("--quipu", None, "https://example.test", "test", G)


_REAL_SCHEMA_CHECK = seeds_plate.uses_native_schema


@pytest.fixture(autouse=True)
def native_schema(monkeypatch):
    monkeypatch.setattr(seeds_plate, "uses_native_schema", lambda *a, **kw: True)
    monkeypatch.setattr(seeds_plate, "owner_shape_supported", lambda *a, **kw: True)


def fields(id="test-held", **overrides):
    row = {
        "id": id,
        "title": "actual work",
        "status": "in_progress",
        "assignee": "worker",
        "priority": 1,
    }
    row.update(overrides)
    inverse = {v: k for k, v in seeds_plate.FIELDS.items()}
    return [
        {
            "subject": seeds_plate.SEEDS + "item/" + id,
            "graph": G,
            "predicate": inverse[k],
            "value": v,
        }
        for k, v in row.items()
    ]


def answer(wire):
    return {"rows": wire, "count": len(wire), "truncated": False}


def reader(monkeypatch, wire):
    tracker = SdTracker(quipu=PROOF.quipu_url, prefix="test")
    monkeypatch.setattr(tracker, "prove_store", lambda: PROOF)
    monkeypatch.setattr(
        seeds_plate, "_query", lambda proof, query, timeout: answer(wire)
    )
    monkeypatch.setattr(
        tracker,
        "_bd",
        lambda *args: (_ for _ in ()).throw(AssertionError("hydration escaped")),
    )
    return br.plate_reader(tracker, require_complete=True)


def test_held_positive_and_empty_control(monkeypatch):
    assert reader(monkeypatch, fields())("worker").id == "test-held"
    assert reader(monkeypatch, [])("worker") is None


def test_owner_scope_and_lean_fields_on_actual_request(monkeypatch):
    observed = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, size):
            return json.dumps(answer(fields())).encode()

    def send(request, timeout):
        observed.append(json.loads(request.data)["query"])
        assert request.full_url == PROOF.quipu_url + "/query"
        return Response()

    monkeypatch.setattr(seeds_plate, "urlopen", send)
    assert seeds_plate.owner_rows(PROOF, "rig/worker").exact()[0]["id"] == "test-held"
    query = observed[0]
    assert "rig%2Fworker" in query and '"worker"' in query
    assert G + "#seeds-ephemeral" in query
    assert (
        "description" not in query and "notes" not in query and "retained" not in query
    )


@pytest.mark.parametrize(
    "change",
    [
        {"title": None},
        {"status": "weird"},
        {"priority": True},
        {"priority": 5},
        {"assignee": "other"},
    ],
)
def test_invalid_candidate_is_unknown_never_empty(monkeypatch, change):
    with pytest.raises(RuntimeError, match="plate"):
        reader(monkeypatch, fields(**change))("worker")


def test_failure_has_no_hydration_fallback(monkeypatch):
    tracker = SdTracker(quipu=PROOF.quipu_url, prefix="test")
    monkeypatch.setattr(tracker, "prove_store", lambda: PROOF)
    monkeypatch.setattr(
        seeds_plate, "_query", lambda *a: (_ for _ in ()).throw(OSError("offline"))
    )
    monkeypatch.setattr(tracker, "_bd", lambda *a: pytest.fail("fallback hydration"))
    with pytest.raises(RuntimeError, match="offline"):
        br.plate_reader(tracker, require_complete=True)("worker")


def test_held_rank_messages_and_deferral_excluded(monkeypatch):
    wire = fields("test-message", title="inbox: not work", status="hooked")
    wire += fields("test-deferred", status="deferred")
    wire += fields("test-open", status="open", priority=0)
    wire += fields()
    assert reader(monkeypatch, wire)("worker").id == "test-held"


def test_ambiguous_ephemeral_shadow_is_unknown(monkeypatch):
    wire = fields()
    wire += [dict(wire[0], graph=G + "#seeds-ephemeral")]
    with pytest.raises(RuntimeError, match="shared and ephemeral"):
        reader(monkeypatch, wire)("worker")


def test_date_and_label_values_are_preserved(monkeypatch):
    wire = fields(
        defer_until={"datatype": "xsd:dateTime", "value": "2099-01-01T00:00:00Z"},
        labels="desk",
    )
    monkeypatch.setattr(seeds_plate, "_query", lambda *a: answer(wire))
    row = seeds_plate.owner_rows(PROOF, "worker").exact()[0]
    assert row["labels"] == ["desk"] and row["defer_until"].startswith("2099")


@pytest.mark.parametrize(
    "payload",
    [
        {"rows": [], "count": 1, "truncated": False},
        {"rows": [], "count": 0, "truncated": True},
        {"rows": [], "count": 0},
    ],
)
def test_incomplete_wire_is_unknown(monkeypatch, payload):
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def read(self, size):
            return json.dumps(payload).encode()

    monkeypatch.setattr(seeds_plate, "urlopen", lambda *a, **k: Response())
    assert not seeds_plate.owner_rows(PROOF, "worker").complete


def test_projected_readiness_drives_open_rank_and_preserves_unknown(monkeypatch):
    tracker = SdTracker(quipu=PROOF.quipu_url, prefix="test")
    monkeypatch.setattr(tracker, "prove_store", lambda: PROOF)
    wire = fields("test-a", status="open") + fields("test-z", status="open")

    def query(proof, query, timeout):
        if "AS ?subject" in query:
            return answer(wire)
        assert "blockedOn" in query and "related" not in query
        return answer([{"id": "test-z"}])

    monkeypatch.setattr(seeds_plate, "_query", query)
    monkeypatch.setattr(tracker, "_bd", lambda *a: pytest.fail("CLI hydration"))
    assert br.plate_reader(tracker, require_complete=True)("worker").id == "test-z"
    monkeypatch.setattr(
        seeds_plate, "_query", lambda *a: (_ for _ in ()).throw(OSError("offline"))
    )
    assert not tracker.plate_ready_ids("worker").complete


def test_aggregate_counts_have_no_payload_read_and_validate_negative(monkeypatch):
    queries = []

    def query(proof, query, timeout):
        queries.append(query)
        assert "COUNT(DISTINCT ?s)" in query and "description" not in query
        return answer([{"n": 2 if "?priority <= 1" in query else 5}])

    monkeypatch.setattr(seeds_plate, "_query", query)
    assert seeds_plate.unassigned_counts(PROOF) == (5, 2)
    assert len(queries) == 2
    monkeypatch.setattr(seeds_plate, "_query", lambda *a: answer([{"n": False}]))
    with pytest.raises(ValueError):
        seeds_plate.unassigned_counts(PROOF)


@pytest.mark.parametrize("revision", [True, False])
def test_format_probe_distinguishes_legacy_without_false_empty(monkeypatch, revision):
    queries = []
    monkeypatch.setattr(
        seeds_plate,
        "_query",
        lambda proof, q, t: queries.append(q) or {"result": revision},
    )
    assert _REAL_SCHEMA_CHECK(PROOF) is (not revision)
    assert len(queries) == 1
    assert G in queries[0] and G + "#seeds-ephemeral" in queries[0]


def test_schema_read_failure_has_no_fallback(monkeypatch):
    tracker = SdTracker(quipu=PROOF.quipu_url, prefix="test")
    monkeypatch.setattr(tracker, "prove_store", lambda: PROOF)
    monkeypatch.setattr(
        seeds_plate,
        "uses_native_schema",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("format offline")),
    )
    monkeypatch.setattr(tracker, "_bd", lambda *a: pytest.fail("hydration fallback"))
    with pytest.raises(RuntimeError, match="format offline"):
        br.plate_reader(tracker, require_complete=True)("worker")


def test_disappeared_candidate_is_unknown(monkeypatch):
    calls = []

    def query(proof, query, timeout):
        calls.append(query)
        return (
            answer([{"subject": seeds_plate.SEEDS + "item/test-held", "graph": G}])
            if len(calls) == 1
            else answer([])
        )

    monkeypatch.setattr(seeds_plate, "_query", query)
    result = seeds_plate.owner_rows(PROOF, "worker")
    assert not result.complete and "disappeared" in result.caveat


def test_field_from_other_graph_is_unknown(monkeypatch):
    calls = []

    def query(proof, query, timeout):
        calls.append(query)
        if len(calls) == 1:
            return answer(
                [{"subject": seeds_plate.SEEDS + "item/test-held", "graph": G}]
            )
        return answer([dict(row, graph=G + "#seeds-ephemeral") for row in fields()])

    monkeypatch.setattr(seeds_plate, "_query", query)
    assert not seeds_plate.owner_rows(PROOF, "worker").complete


def test_readiness_response_cannot_escape_its_batch(monkeypatch):
    rows = [{"id": f"test-{i}", "status": "open"} for i in range(251)]
    monkeypatch.setattr(seeds_plate, "_query", lambda *a: answer([{"id": "test-250"}]))
    with pytest.raises(ValueError, match="readiness"):
        seeds_plate.unblocked_ids(PROOF, rows)


def test_attribution_uses_declared_headers_and_no_bearer(monkeypatch):
    # This positive control declares a harness instead of inheriting the
    # operator shell's context. A stale SHANTY_AGENT alone stays UNKNOWN.
    for key in ("QUIPU_AGENT", "QUIPU_SESSION", "SEEDS_AGENT_NAME"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CODEX_HOME", "fixture-harness")
    monkeypatch.setenv("SHANTY_AGENT", "worker")
    monkeypatch.setenv("SEEDS_SESSION", "test-session")

    def send(request, timeout):
        assert request.get_header("X-quipu-agent") == "worker"
        assert request.get_header("X-quipu-session") == "test-session"
        assert request.get_header("Authorization") is None

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def read(self, size):
                return json.dumps(answer([])).encode()

        return Response()

    monkeypatch.setattr(seeds_plate, "urlopen", send)
    assert seeds_plate.owner_rows(PROOF, "worker").exact() == []


def test_feed_projection_scopes_idle_owners_and_unassigned(monkeypatch):
    seen = []
    wire = fields("test-owned", assignee="worker", status="in_progress")
    wire += fields("test-unassigned", assignee="", status="open")

    def query(proof, text, timeout):
        seen.append(text)
        return answer(wire)

    monkeypatch.setattr(seeds_plate, "_query", query)
    rows = seeds_plate.owner_rows(PROOF, None, feed_owners=("rig/worker",)).exact()
    assert {row["id"] for row in rows} == {"test-owned", "test-unassigned"}
    discovery = seen[0]
    assert "(^|/|%2F)(worker)$" in discovery
    assert 'FILTER(STR(?owner) != "")' in discovery
    assert G + "#seeds-ephemeral" in discovery
    assert "description" not in discovery


@pytest.mark.parametrize("fault", ["foreign", "disappeared", "offline"])
def test_feed_incomplete_read_never_hydrates_or_claims_empty(monkeypatch, fault):
    tracker = SdTracker(quipu=PROOF.quipu_url, prefix="test")
    monkeypatch.setattr(tracker, "prove_store", lambda: PROOF)
    monkeypatch.setattr(tracker, "_bd", lambda *a: pytest.fail("SDK hydration"))
    calls = []

    def query(proof, text, timeout):
        calls.append(text)
        if fault == "offline":
            raise OSError("unavailable")
        if fault == "disappeared" and len(calls) > 1:
            return answer([])
        return answer(fields(assignee="other" if fault == "foreign" else "worker"))

    monkeypatch.setattr(seeds_plate, "_query", query)
    from shantytown.answer import PartialAnswer
    with pytest.raises(PartialAnswer):
        tracker.feed_rows(["worker"])


@pytest.mark.parametrize("owner", ["worker", "rig/crew/worker",
                                    seeds_plate.SEEDS + "principal/rig%2Fcrew%2Fworker"])
def test_feed_haul_preserves_short_and_crew_path_owners(monkeypatch, owner):
    monkeypatch.setattr(seeds_plate, "_query", lambda *a: answer(fields(assignee=owner)))
    row = seeds_plate.owner_rows(PROOF, None, feed_owners=("worker",)).exact()[0]
    assert row["assignee"].split("/")[-1] == "worker"


def test_roster_batch_preserves_hooked_held_and_empty_without_per_owner_reads(monkeypatch):
    tracker = SdTracker(quipu=PROOF.quipu_url, prefix="test")
    monkeypatch.setattr(tracker, "prove_store", lambda: PROOF)
    wire = fields("test-a", assignee="a", status="hooked")
    wire += fields("test-b", assignee="rig/b", status="in_progress")
    queries = []
    monkeypatch.setattr(seeds_plate, "_query", lambda p, q, t: queries.append(q) or answer(wire))
    monkeypatch.setattr(tracker, "_bd", lambda *a: pytest.fail("SDK hydration"))
    read = br.plate_reader(tracker, require_complete=True, owners=["a", "rig/b", "empty"])
    assert read("a").id == "test-a"
    assert read("rig/b").id == "test-b"
    assert read("empty") is None
    assert len(queries) == 2
    assert '"hooked"' in queries[0]
    assert "VALUES ?s" in queries[1]
    assert "GRAPH ?g" not in queries[1]
    # Fresh render replaces the reader-local observation.
    monkeypatch.setattr(seeds_plate, "_query", lambda *a: answer([]))
    fresh = br.plate_reader(tracker, require_complete=True, owners=["a"])
    assert fresh("a") is None


def test_roster_outage_is_unknown_for_every_named_owner_without_fallback(monkeypatch):
    tracker = SdTracker(quipu=PROOF.quipu_url, prefix="test")
    monkeypatch.setattr(tracker, "prove_store", lambda: PROOF)
    monkeypatch.setattr(seeds_plate, "_query", lambda *a: (_ for _ in ()).throw(OSError("503")))
    monkeypatch.setattr(tracker, "_bd", lambda *a: pytest.fail("SDK hydration"))
    read = br.plate_reader(tracker, require_complete=True, owners=["a", "b"])
    for owner in ["a", "b"]:
        with pytest.raises(RuntimeError, match="503"):
            read(owner)


def test_roster_scope_cannot_include_unassigned_work(monkeypatch):
    seen = []
    monkeypatch.setattr(seeds_plate, "_query", lambda p, q, t: seen.append(q) or answer(fields("test-a", assignee="a")))
    assert seeds_plate.owner_rows(PROOF, None, plate_owners=("a",)).exact()[0]["id"] == "test-a"
    assert 'FILTER(STR(?owner) != "")' not in seen[0]


def test_global_queue_projection_failure_does_not_hydrate(monkeypatch, tmp_path):
    from shantytown import feed_check
    tracker = SdTracker(quipu=PROOF.quipu_url, prefix="test")
    monkeypatch.setattr(tracker, "prove_store", lambda: PROOF)
    monkeypatch.setattr(seeds_plate, "_query", lambda *a: (_ for _ in ()).throw(OSError("503")))
    monkeypatch.setattr(tracker, "_bd", lambda *a: pytest.fail("SDK fallback"))
    from shantytown.answer import PartialAnswer
    with pytest.raises(PartialAnswer, match="503"):
        feed_check.queue_state(tmp_path, None, tracker)


@pytest.mark.parametrize("owner", ["", "foreign"])
def test_roster_response_cannot_escape_named_owner_scope(monkeypatch, owner):
    monkeypatch.setattr(seeds_plate, "_query", lambda *a: answer(fields("test-a", assignee=owner)))
    assert not seeds_plate.owner_rows(PROOF, None, plate_owners=("a",)).complete
