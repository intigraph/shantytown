"""Offline work/message boundary fixture, using actual generated SPARQL."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch
import rdflib

parser = argparse.ArgumentParser()
parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[3])
args = parser.parse_args()
sys.path.insert(0, str(args.source))
from shantytown import cli, seeds_plate, feed_check, board_triage
from shantytown.answer import Answer
from shantytown.sd import StoreProof

namespace = "https://example.test/project/demo"
proof = StoreProof("--quipu", None, "https://example.test", "test", namespace)
dataset = rdflib.Dataset()
graph = dataset.graph(rdflib.URIRef(namespace))
titles = ["inbox: repair backup", " mail: repair backup", "  inbox: repair backup",
          "mail: repair backup", "repair backup", "Inbox policy repair backup"]
rows = []
for index, title in enumerate(titles):
    identifier = "test-" + str(index)
    subject = rdflib.URIRef(seeds_plate.SEEDS + "item/" + identifier)
    for predicate, value in [(rdflib.RDF.type, rdflib.URIRef(seeds_plate.SCHEMA + "Action")),
        (rdflib.URIRef(seeds_plate.SEEDS + "ontology/status"), rdflib.Literal("open")),
        (rdflib.URIRef(seeds_plate.SCHEMA + "identifier"), rdflib.Literal(identifier)),
        (rdflib.URIRef(seeds_plate.SCHEMA + "name"), rdflib.Literal(title))]:
        graph.add((subject, predicate, value))
    rows.append(dict(id=identifier, title=title, labels=["inbox"] if index == 5 else []))
def query(proof, text, timeout):
    values = [{str(k): str(v) for k, v in row.asdict().items()} for row in dataset.query(text)]
    return dict(rows=values, count=len(values), truncated=False)
with patch.object(seeds_plate, "_query", query):
    native = seeds_plate.ready_count(proof, now=datetime(2026, 1, 2, tzinfo=timezone.utc))
adapter = SimpleNamespace(tracker=None, ready=lambda: Answer.complete_read(rows, how="fixture"))
with patch.object(feed_check, "TrackerAdapter", lambda *unused: adapter):
    legacy = cli._ready_count(None, None)
selected = board_triage.candidates(dict(id="query", title="repair backup"), rows)
print(json.dumps(dict(native_ready_work=native, legacy_ready_work=legacy,
    triage_titles=[row["title"] for row in selected],
    labelled_work_preserved=any(row["id"] == "test-5" for row in selected)), sort_keys=True))
