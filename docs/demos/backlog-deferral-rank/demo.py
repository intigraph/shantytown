"""Same native-writer fixture, exact shipped v1/v2 queries, local RDFLib engine."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import rdflib

from rdflib import Dataset, Graph, Namespace, URIRef

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from shantytown.backlog_rank import ordered  # noqa: E402

binary = str(Path(sys.argv[1]).resolve())
with tempfile.TemporaryDirectory(prefix="backlog-observed-demo-") as directory:
    root = Path(directory)
    board = "urn:test:backlog-observed-demo"
    command = [binary, "--store", str(root / "fixture.db"), "--graph", board,
               "--actor", "demo"]

    def run(*args):
        return subprocess.run(command + list(args), cwd=root, text=True,
                              capture_output=True, check=True).stdout

    older = json.loads(run("create", "Older technical fixture", "--priority", "1", "--json"))["id"]
    time.sleep(1.05)  # Native CLI timestamps use whole seconds; keep the age control distinct.
    observed = json.loads(run("create", "Observed technical fixture", "--priority", "1", "--json"))["id"]
    for _ in range(4):
        run("defer", observed)
    run("undefer", observed)
    candidates = json.loads(run("show", older, observed, "--json"))
    assert isinstance(candidates, list) and len(candidates) == 2
    original = json.dumps(candidates, sort_keys=True)
    run("export", "--to", str(root / "pendant"))
    data = Dataset()
    normalizing = rdflib.NORMALIZE_LITERALS
    rdflib.NORMALIZE_LITERALS = False
    try:
        data.graph(URIRef(board)).parse(root / "pendant/export.nt", format="nt")
    finally:
        rdflib.NORMALIZE_LITERALS = normalizing
    q = Namespace("https://quipu.dev/ontology/")
    now = datetime.now(timezone.utc)
    params = {"board": board, "owner": "demo", "now": now.isoformat().replace("+00:00", "Z")}
    ids = sorted([older, observed])
    params.update({f"id{i:02}": ids[i] if i < len(ids) else "" for i in range(64)})
    labels = {older: "older", observed: "observed"}

    def execute(version):
        definition = Graph().parse(ROOT / f"queries/seeds-work-rank-v{version}.ttl")
        template = str(definition.value(URIRef(f"urn:quipu:query:seeds_work_rank_v{version}"), q.sparqlTemplate))
        for key, value in params.items():
            template = template.replace("{" + key + "}", value)
        return [{str(key): value.toPython() for key, value in row.asdict().items()}
                for row in data.query(template)]

    before = execute(1)
    after = execute(2)
    assert [row["id"] for row in before] == [older, observed]
    def reader(_root, name, supplied, **bounds):
        assert name == "seeds_work_rank_v2" and supplied == {k: v for k, v in params.items() if v != ""}
        assert bounds == {"limit": 65, "timeout": 8}
        return after
    selected = ordered(None, candidates, owner="demo", board=board, reader=reader, now=now)
    assert [row["id"] for row in selected] == [observed, older]
    assert json.dumps(candidates, sort_keys=True) == original
    print(json.dumps({"profile": "v1", "order": [labels[row["id"]] for row in before]}))
    print(json.dumps({"profile": "v2", "order": [labels[row["id"]] for row in after],
                      "observed_lower_bound": after[0]["observed_deferral_writes"],
                      "historical_state": after[1]["deferral_observation"]}))
    print("native SDK revision/priority/status/owner witnesses matched; candidates unchanged; zero dispatches")
