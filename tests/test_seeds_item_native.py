"""Optional native interoperability check; never opens a deployment store.

Set QUIPU_NATIVE_TEST_BIN to a reviewed executable to run these controls.
No executable is downloaded and no server or credential is used.
"""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace

import pytest

from shantytown import seeds_item as item

GRAPH = "https://seeds.local/project/native-reader-test"
BIN = os.environ.get("QUIPU_NATIVE_TEST_BIN")
pytestmark = pytest.mark.skipif(not BIN, reason="explicit native Quipu executable required")


def native_rows(output):
    """Decode only the fixed synthetic fixture's CLI table; refuse format drift."""
    lines = output.strip().splitlines()
    if output.strip() in ("0 results", "No results"):
        return []
    assert lines[0] == "graph\ts\tp\to\tkind"
    assert set(lines[1]) == {"-"}
    count = re.fullmatch(r"(\d+) results?", lines[-1])
    assert count is not None
    rows = []
    for line in lines[2:-1]:
        if not line:
            continue
        fields = line.split("\t")
        assert len(fields) == 5
        rows.append(dict(zip(("graph", "s", "p"), fields[:3]),
                         o=json.loads(fields[3]), kind=json.loads(fields[4])))
    assert len(rows) == int(count[1])
    return rows


def native_fixture(root, binary, *, unrelated=30):
    """Prepare a synthetic store; also used by the repeatable query demo."""
    binary = Path(binary).resolve()
    assert binary.is_file()
    root.mkdir(parents=True, exist_ok=True)
    database = root / "synthetic.db"
    env = {key: value for key, value in os.environ.items()
           if key in {"HOME", "PATH", "TMPDIR", "LANG", "LC_ALL",
                      "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME"}}

    def run(*args):
        result = subprocess.run([str(binary), *args, "--db", str(database)],
                                env=env, text=True, capture_output=True, timeout=10)
        assert result.returncode == 0, result.stderr
        return result.stdout

    def facts(name, *, priority='"0"^^<' + item.XSD + 'integer>'):
        subject = "<" + item.SEEDS + "item/" + name + ">"
        return [f"{subject} <{item.TYPE}> <{item.SCHEMA}Action> .",
                f"{subject} <{item.SCHEMA}identifier> {json.dumps(name)} .",
                f"{subject} <{item.SCHEMA}name> {json.dumps(name)} .",
                f'{subject} <{item.SEEDS}ontology/status> "open" .',
                f"{subject} <{item.SEEDS}ontology/priority> {priority} ."]

    def block(source, target):
        return (f"<{item.SEEDS}item/{source}> <{item.BLOCKS}> "
                f"<{item.SEEDS}item/{target}> .")

    primary = []
    for name in ("plain", "known", "target", "missing", "cross", "dated",
                 "duplicate-target", "duplicate-source", "multiple"):
        primary += facts(name)
    primary += facts("bad-priority", priority='"0"')
    primary += [block("known", "target"), block("missing", "unavailable"),
                block("cross", "ephemeral-target"),
                block("multiple", "target"),
                f'<{item.SEEDS}item/multiple> <{item.SCHEMA}isPartOf> '
                f'<{item.SEEDS}item/target> .',
                block("duplicate-source", "duplicate-target"),
                f'<{item.SEEDS}item/dated> <{item.SCHEMA}scheduledTime> '
                f'"2026-10-20"^^<{item.XSD}date> .']
    ephemeral = facts("ephemeral-target") + facts("ephemeral-source")
    ephemeral += facts("duplicate-target") + [block("ephemeral-source", "target")]
    # Unrelated metadata must not leak into a constant subject or dependency read.
    for number in range(unrelated):
        primary += facts(f"unrelated-primary-{number}")
        ephemeral += facts(f"unrelated-ephemeral-{number}")
    for index, (graph, triples) in enumerate(((GRAPH, primary),
                                             (GRAPH + "#seeds-ephemeral", ephemeral))):
        run("graph", "create", graph)
        data = ("\n".join(triples) + "\n").encode()
        path = root / f"fixture-{index}.nt"
        path.write_bytes(data)
        run("ingest", str(path), "--graph", graph,
            "--timestamp", "2026-10-20T00:00:00Z", "--format", "nt",
            "--declare-count", str(len(triples)),
            "--declare-sha256", hashlib.sha256(data).hexdigest())
    return run


@pytest.fixture(scope="module")
def native(tmp_path_factory):
    return native_fixture(tmp_path_factory.mktemp("native-item-reader"), BIN)


def read(monkeypatch, native, identifier):
    calls = []

    def query(_proof, text, _timeout, *, verbose=False):
        assert verbose is True
        calls.append(text)
        return {"rows": native_rows(native("read", text))}

    monkeypatch.setattr(item, "_query", query)
    tracker = SimpleNamespace(_use_remote_projection=lambda: True,
                              prove_store=lambda: SimpleNamespace(graph=GRAPH), timeout=10)
    result = item.read_item(tracker, identifier)
    assert len(calls) == 1
    return result


@pytest.mark.parametrize("identifier,blockers", [
    ("plain", ()), ("known", ("target",)), ("missing", ("unavailable",)),
    ("cross", ("ephemeral-target",)), ("ephemeral-source", ("target",)),
    ("dated", ()), ("multiple", ("target",)),
])
def test_native_item_and_cross_graph_dependencies(monkeypatch, native, identifier, blockers):
    result = read(monkeypatch, native, identifier)
    assert result.id == result.title == identifier
    assert result.priority == 0 and result.status == "open"
    assert result.open_blockers == blockers
    assert result.defer_until == ("2026-10-20" if identifier == "dated" else None)


@pytest.mark.parametrize("identifier,error", [
    ("absent", LookupError), ("bad-priority", ValueError),
    ("duplicate-source", ValueError),
])
def test_native_invalid_or_ambiguous_metadata_refuses(monkeypatch, native, identifier, error):
    with pytest.raises(error):
        read(monkeypatch, native, identifier)


def test_native_shared_target_retains_bag_multiplicity(native):
    query = item._fields_query((GRAPH, GRAPH + "#seeds-ephemeral"),
                              item.SEEDS + "item/multiple")
    rows = native_rows(native("read", query))
    target = [row for row in rows if row["s"] == item.SEEDS + "item/target"]
    counts = Counter(tuple(sorted(row.items())) for row in target)
    assert len(counts) == 4 and set(counts.values()) == {2}
