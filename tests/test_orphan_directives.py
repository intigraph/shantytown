import pytest

from shantytown import orphan_directives as od
from shantytown.anchor import Anchoring
from shantytown.protocols import Agent

NS = "https://crew.example/onto/"


def configure(root, query="orphans"):
    line = f'SHANTY_ORPHAN_DIRECTIVES_QUERY="{query}"\n' if query else ""
    (root / "shantytown.toml").write_text("[env]\n" + line)


def rows(*names):
    return [{"directive": NS + n} for n in names]


def test_undeclared_query_renders_nothing_and_never_reads(tmp_path, monkeypatch):
    monkeypatch.delenv(od.KEY, raising=False)
    configure(tmp_path, query=None)
    def reader(*a, **k):
        raise AssertionError("must not read when the deployment declared no query")
    assert od.load(tmp_path, reader=reader) is None
    assert od.render(None) == ""


def test_rows_render_exact_count_and_local_names(tmp_path):
    configure(tmp_path)
    calls = []
    def reader(root, name, params, *, limit):
        calls.append((name, params, limit))
        return rows("op-directive-a", "op-directive-b")
    found = od.load(tmp_path, reader=reader)
    assert calls == [("orphans", {}, od.LIMIT)]
    text = od.render(found)
    assert "ORPHAN DIRECTIVES (2)" in text and "op-directive-a, op-directive-b" in text


def test_long_list_keeps_exact_count_and_says_how_many_are_hidden(tmp_path):
    configure(tmp_path)
    names = [f"d{i:02d}" for i in range(od.SHOWN + 3)]
    text = od.render(od.load(tmp_path, reader=lambda *a, **k: rows(*names)))
    assert f"ORPHAN DIRECTIVES ({len(names)})" in text and "(+3 more)" in text


def test_empty_answer_says_none_not_unknown(tmp_path):
    configure(tmp_path)
    assert od.render(od.load(tmp_path, reader=lambda *a, **k: [])) == "  ORPHAN DIRECTIVES: none"


@pytest.mark.parametrize("answer", [[{"label": "no iri"}], ["not a row"], rows("x", "x"), [{"directive": ""}]])
def test_malformed_rows_are_unknown(tmp_path, answer):
    configure(tmp_path)
    found = od.load(tmp_path, reader=lambda *a, **k: answer)
    assert found.unknown and "UNKNOWN" in od.render(found)


def test_refused_or_overflowing_read_is_unknown_and_hides_remote_text(tmp_path):
    configure(tmp_path)
    def reader(*a, **k):
        raise ValueError("named query completeness UNKNOWN at https://secret.example/ask")
    text = od.render(od.load(tmp_path, reader=reader))
    assert "UNKNOWN" in text and "secret.example" not in text


def test_anchor_prints_the_section_under_directives_only_when_given():
    me = Agent(name="boss", role="administrator")
    base = Anchoring(me=me, item=None, lead=None, lead_up=None, context=[], knowledge=[], admin="boss")
    assert "ORPHAN DIRECTIVES" not in base.render()
    base.orphan_directives = "  ORPHAN DIRECTIVES (1): no seed tracks these.\n    d1"
    out = base.render()
    assert out.index("DIRECTIVES") < out.index("ORPHAN DIRECTIVES (1)") < out.index("ON YOUR PLATE")
