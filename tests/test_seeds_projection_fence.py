"""Exact owner reads tolerate unrelated commits, never membership changes."""
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from shantytown import seeds_plate as plate
from shantytown import seeds_read_cache as cache

G = "https://example.test/board"
S = plate.SEEDS + "item/test-held"


@pytest.fixture
def wire(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.delenv("ST_SEEDS_READ_CACHE", raising=False)
    monkeypatch.setattr(plate, "owner_shape_supported", lambda *a, **kw: True)
    state = dict(tx=10, feeds=[], queries=0, mode="unrelated-entity", store="fixture")
    def watermark(*args):
        state["tx"] += state.get("step", 1000)  # Writes during every query.
        return state["store"], state["tx"]
    monkeypatch.setattr(cache, "_watermark", watermark)
    class Response:
        status = 200
        def __init__(self, data): self.data = data
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size): return json.dumps(self.data).encode()
    def send(request, timeout):
        if request.get_method() == "POST":
            state["queries"] += 1
            values = dict(id="test-held", title=state.get("title", "actual work"), status="in_progress",
                          assignee="worker", priority=1, issue_type="task")
            inverse = {v: k for k, v in plate.FIELDS.items()}
            rows = [dict(subject=S, graph=G, predicate=inverse[k], value=v)
                    for k, v in values.items()]
            return Response(dict(rows=rows, count=len(rows), truncated=False))
        parsed = urlsplit(request.full_url)
        assert parsed.path == "/changes"
        params = parse_qs(parsed.query)
        graph, since = params["graph"][0], int(params["since"][0])
        state["feeds"].append((graph, since))
        entity = plate.SEEDS + "item/other"
        attribute = state.get("attribute", plate.SCHEMA + "description")
        mode = state["mode"]
        if mode == "returned": entity = S
        if mode == "membership": attribute = plate.SCHEMA + "agent"
        if mode == "status": attribute = plate.SEEDS + "ontology/status"
        if mode == "blocker": attribute = "https://scbrown.github.io/quechua/ns#blockedOn"
        records = [] if mode == "unrelated-graph" else [
            dict(tx=since + 1, graph=graph, entity=entity, attribute=attribute, op="assert")]
        if mode == "past-returned":
            records = ([dict(tx=11, graph=graph, entity=S, attribute=attribute, op="assert")]
                       if since < 11 <= state["tx"] else [])
        if mode in ("paged", "page-cap", "epoch-change"):
            records = [dict(tx=since + n, graph=graph, entity=entity, attribute=attribute, op="assert")
                       for n in (1, 2)] if mode == "page-cap" or len(state["feeds"]) % 2 else []
        result = dict(records=records, since=since,
                      next_tx=max((r["tx"] for r in records), default=since), watermark_tx=state["tx"],
                      capture="new_values", source=dict(store_id=state["store"], log_epoch="epoch"))
        if mode == "epoch-change" and len(state["feeds"]) > 1:
            result["source"]["log_epoch"] = "replacement-epoch"
        if mode == "truncated": result["truncated"] = True
        if mode == "store-replaced": result["source"]["store_id"] = "foreign"
        if mode == "malformed": result["records"][0].pop("attribute")
        if mode == "offline": raise OSError("change feed unavailable")
        return Response(result)
    monkeypatch.setattr(plate, "urlopen", send)
    return SimpleNamespace(quipu_url="https://example.test", graph=G), state


@pytest.mark.parametrize("mode", ["unrelated-graph", "unrelated-entity"])
def test_unrelated_commits_do_not_empty_exact_owner_answers(wire, mode):
    proof, state = wire
    state["mode"] = mode
    assert plate.owner_rows(proof, "worker").exact()[0]["id"] == "test-held"
    assert {g for g, _ in state["feeds"]} == {G, G + "#seeds-ephemeral"}
    assert state["queries"] == 2


SCHEDULING_FIELDS = (
    plate.SEEDS + "ontology/priority",
    plate.SEEDS + "ontology/rank",
    plate.SCHEMA + "scheduledTime",
    plate.SEEDS + "ontology/deferUntil",
)


@pytest.mark.parametrize("attribute", SCHEDULING_FIELDS)
def test_unselected_scheduling_changes_do_not_restart_candidates(wire, attribute):
    proof, state = wire
    state["attribute"] = attribute
    assert plate.owner_rows(proof, "worker").exact()[0]["id"] == "test-held"
    assert state["queries"] == 2
    assert len(state["feeds"]) == 2


@pytest.mark.parametrize("attribute", SCHEDULING_FIELDS)
def test_continuously_changed_selected_scheduling_still_refuses(wire, attribute):
    proof, state = wire
    state.update(mode="returned", attribute=attribute)
    assert not plate.owner_rows(proof, "worker").complete
    assert state["queries"] == 4  # Initial selection/fields, then two field repairs.


@pytest.mark.parametrize("mode", ["returned", "membership", "status", "blocker"])
def test_returned_entity_or_membership_change_never_becomes_exact(wire, mode):
    proof, state = wire
    state["mode"] = mode
    result = plate.owner_rows(proof, "worker")
    assert not result.complete
    assert state["feeds"]  # Exercise scoped evidence, not global-tx refusal.
    assert state["queries"] == (4 if mode == "returned" else 6)
    # Payload repairs share three passes; membership repeats all queries.


@pytest.mark.parametrize("mode", ["truncated", "store-replaced", "malformed", "offline"])
def test_unusable_change_evidence_is_unknown_not_an_empty_success(wire, mode):
    proof, state = wire
    state["mode"] = mode
    assert not plate.owner_rows(proof, "worker").complete
    assert state["feeds"]
    assert state["queries"] == 2  # Non-transient proof failures are not retried.


def test_relevant_change_invalidates_older_hits_before_retry(wire):
    proof, state = wire
    state.update(step=0, title="before")
    assert plate.owner_rows(proof, "worker").exact()[0]["title"] == "before"
    state.update(step=1, title="after", mode="past-returned")
    assert plate.owner_rows(proof, "worker").exact()[0]["title"] == "after"
    assert state["feeds"][0][1] == 10  # Include the older cached observation.
    assert state["queries"] == 3  # One fresh field repair; no candidate restart.


def test_full_change_pages_are_drained_before_claiming_absence(wire, monkeypatch):
    proof, state = wire
    state["mode"] = "paged"
    monkeypatch.setattr(cache, "_CHANGE_TX_LIMIT", 2)
    assert plate.owner_rows(proof, "worker").exact()
    assert len(state["feeds"]) == 4
    assert state["feeds"][1][1] == state["feeds"][0][1] + 2


@pytest.mark.parametrize("mode", ["page-cap", "epoch-change"])
def test_incomplete_or_changed_history_never_certifies(wire, monkeypatch, mode):
    proof, state = wire
    state["mode"] = mode
    monkeypatch.setattr(cache, "_CHANGE_TX_LIMIT", 2)
    monkeypatch.setattr(cache, "_CHANGE_PAGES", 2)
    assert not plate.owner_rows(proof, "worker").complete
    assert state["queries"] == 2


def test_projection_misses_publish_only_after_complete_fence(wire):
    proof, state = wire
    state.update(step=0, mode="offline")
    # A store movement is necessary to exercise the unavailable feed.
    marks = iter([("fixture", 10), ("fixture", 11)])
    original = cache._watermark
    from unittest.mock import patch
    with patch.object(cache, "_watermark", side_effect=lambda *a: next(marks)):
        assert not plate.owner_rows(proof, "worker").complete
    assert state["queries"] == 2
    state.update(mode="unrelated-entity", tx=11)
    assert plate.owner_rows(proof, "worker").exact()
    assert state["queries"] == 4  # Neither uncertified miss was published.


def test_projection_uses_one_initial_and_one_final_watermark(wire,monkeypatch):
    proof,state=wire
    state.update(step=0)
    original=cache._watermark
    calls=[]
    def counted(*a):
        calls.append(1)
        return original(*a)
    monkeypatch.setattr(cache,"_watermark",counted)
    assert plate.owner_rows(proof,"worker").exact()
    assert len(calls)==2
    assert state["queries"]==2
    assert plate.owner_rows(proof,"worker").exact()
    assert state["queries"]==2  # Certified entries still accelerate warm reads.


def test_same_store_watermark_regression_is_unknown_not_a_restart(wire,monkeypatch):
    proof,state=wire
    marks=iter([("fixture",10),("fixture",9)])
    monkeypatch.setattr(cache,"_watermark",lambda *a:next(marks))
    assert not plate.owner_rows(proof,"worker").complete
    assert state["queries"]==2


def test_membership_restarts_back_off_inside_the_shared_budget(wire,monkeypatch):
    proof,state=wire
    state['mode']='membership'
    sleeps=[]
    monkeypatch.setattr(cache.time,'sleep',sleeps.append)
    assert not plate.owner_rows(proof,'worker').complete
    assert state['queries']==6
    assert sleeps==[.1,.2]
