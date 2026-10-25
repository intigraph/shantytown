"""Exact work-item context before semantic search (aegis-ayj).

Replays the kota retro: a search for the exact ID answered NO CONTEXT while the
item had eight linked episodes. Each section is its own bounded read, so one
failed read is UNKNOWN and never an empty answer.
"""
from types import SimpleNamespace

import pytest

from shantytown import query_first, seeds_item, work_context
from shantytown.protocols import WorkItem

ONTO = "http://aegis.gastown.local/ontology/"
GRAPH = "https://seeds.local/project/aegis"


def item(**over):
    base = dict(id="aegis-edp", title="Use DNS names only", status="closed", assignee="arnold",
                priority=0, description="", notes="gated on Gold main green",
                defer_until=None, open_blockers=("aegis-spz",), due_at="2026-11-07T21:43:09Z")
    return WorkItem(**{**base, **over})


class Tracker:
    def __init__(self, proof=None, error=None):
        self.proof, self.error = proof, error

    def prove_store(self):
        if self.error:
            raise self.error
        return self.proof


PROOF = SimpleNamespace(quipu_url="http://quipu.test", graph=GRAPH)
EPISODE = {"act": ONTO + "episode_x", "when": {"datatype": "xsd:dateTime", "value": "2026-10-25T02:25:50Z"},
           "label": "arnold-edp-final-end", "who": "session s arnold task:aegis-edp",
           "gist": "BEFORE: kota moved\nAFTER: names"}


def answer(rows_for):
    """A fake /query: rows chosen by which section's query it is."""
    seen = []

    def query(proof, sparql, timeout, *, verbose=False):
        seen.append(sparql)
        for key, rows in rows_for.items():
            if key in sparql:
                if isinstance(rows, Exception):
                    raise rows
                return {"rows": rows}
        return {"rows": []}
    return query, seen


@pytest.fixture
def known(monkeypatch):
    monkeypatch.setattr(seeds_item, "read_item", lambda tracker, item_id: item())


def run(monkeypatch, rows_for, tracker=None):
    query, seen = answer(rows_for)
    monkeypatch.setattr(work_context, "_query", query)
    ctx = work_context.context(tracker or Tracker(PROOF), "aegis-edp", onto=ONTO)
    return ctx, work_context.render(ctx), seen


def test_exact_reads_surface_linked_episodes_a_search_would_miss(monkeypatch, known):
    ctx, text, seen = run(monkeypatch, {
        "aboutWorkItem": [EPISODE],
        "parentItem": [{"position": 31, "when": "2026-10-25T02:25:57Z",
                        "author": "https://seeds.local/principal/arnold", "gist": "END recap"}],
        "trackedBy": [{"ruling": ONTO + "r1", "label": "dns-names-only", "type": ONTO + "Directive"}],
    })
    assert "EXACT CONTEXT for aegis-edp" in text
    assert "[closed] P0 Use DNS names only @arnold" in text
    assert "blocked on: aegis-spz" in text and "notes: gated on Gold main green" in text
    assert "episodes (1):" in text and "2026-10-25T02:25:50Z arnold-edp-final-end: BEFORE: kota moved AFTER: names" in text
    assert "#31 2026-10-25T02:25:57Z arnold: END recap" in text
    assert "dns-names-only" in text
    assert "is not absence" in text
    # Every read names its subject exactly; none is an unbound scan.
    assert all(f"<{ONTO}aegis-edp>" in q or "<https://seeds.local/item/aegis-edp>" in q for q in seen)
    assert not any("CONTAINS" in q or "REGEX" in q for q in seen)
    assert all("LIMIT" in q for q in seen)


def test_one_failed_read_is_unknown_and_the_others_still_answer(monkeypatch, known):
    _, text, _ = run(monkeypatch, {"aboutWorkItem": TimeoutError("timed out"),
                                   "trackedBy": [], "parentItem": []})
    assert "episodes: UNKNOWN (TimeoutError: timed out); this is not an empty answer" in text
    assert f"rulings: 0 found at ?ruling <{ONTO}trackedBy> <{ONTO}aegis-edp>" in text
    assert "comments: 0 found at https://seeds.local/item/aegis-edp in " + GRAPH in text


def test_an_absent_item_is_named_not_rendered_as_empty(monkeypatch):
    def absent(tracker, item_id):
        raise LookupError("exact native item absent")
    monkeypatch.setattr(seeds_item, "read_item", absent)
    _, text, _ = run(monkeypatch, {})
    assert "item: UNKNOWN (item absent: exact native item absent)" in text


def test_an_unproven_store_makes_every_graph_section_unknown(monkeypatch, known):
    _, text, seen = run(monkeypatch, {}, tracker=Tracker(error=RuntimeError("no seeds where")))
    assert seen == []
    for name in ("comments", "episodes", "rulings"):
        assert f"{name}: UNKNOWN (store unproven: RuntimeError: no seeds where)" in text


def test_a_malformed_id_is_refused_before_any_read(monkeypatch):
    with pytest.raises(ValueError):
        work_context.context(Tracker(PROOF), "../etc", onto=ONTO)


def test_query_first_directive_starts_exact_and_says_no_context_is_not_absence():
    text = query_first.DIRECTIVE
    assert "st work item context <id>" in text
    assert text.index("st work item context") < text.index("quipu_search")
    assert "NO CONTEXT search answer is not absence" in text


def test_begin_task_prints_exact_context_for_a_seeds_board(monkeypatch, tmp_path, capsys, known):
    from shantytown import cli
    query, _ = answer({"aboutWorkItem": [EPISODE]})
    monkeypatch.setattr(work_context, "_query", query)
    monkeypatch.setattr(cli, "_raw_tracker", lambda a, default="files": Tracker(PROOF))
    monkeypatch.setenv("SHANTY_ONTO_NS", ONTO)
    assert cli.main(["--root", str(tmp_path), "stats", "--begin-task", "aegis-edp"]) == 0
    out = capsys.readouterr().out
    assert "EXACT CONTEXT for aegis-edp" in out and "arnold-edp-final-end" in out


def test_begin_task_on_a_board_without_a_store_proof_prints_no_context(monkeypatch, tmp_path, capsys):
    from shantytown import cli
    monkeypatch.setattr(cli, "_raw_tracker", lambda a, default="files": SimpleNamespace())
    assert cli.main(["--root", str(tmp_path), "stats", "--begin-task", "aegis-edp"]) == 0
    assert "EXACT CONTEXT" not in capsys.readouterr().out


def test_begin_task_never_fails_on_a_context_error(monkeypatch, tmp_path, capsys):
    from shantytown import cli
    def broken(a, default="files"):
        raise OSError("tracker unavailable")
    monkeypatch.setattr(cli, "_raw_tracker", broken)
    assert cli.main(["--root", str(tmp_path), "stats", "--begin-task", "aegis-edp"]) == 0
    assert "exact context UNKNOWN (OSError)" in capsys.readouterr().out
