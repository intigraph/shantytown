#!/usr/bin/env python3
"""Private real SPARQL replay on both spellings, no HTTP or key operations."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import rdflib
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from shantytown import shuttle_runs  # noqa: E402
BASE = '48bb2a84b566cf107214057c4a5e1d05a928080d'
OLD = 'http://aegis.gastown.local/ontology/'
CORE = 'https://w3id.org/intigraph/camayoc/core/ns#'
QP = 'https://w3id.org/intigraph/quipu/ns#'
def fixture(canonical):
    graph = rdflib.Graph()
    subject, workflow = rdflib.URIRef('urn:fixture:run'), rdflib.URIRef('urn:fixture:workflow')
    graph.add((subject, rdflib.RDF.type, rdflib.URIRef((QP if canonical else OLD) + 'WorkflowRun')))
    for name, value in [('runOf', workflow), ('currentState', rdflib.Literal('claimed'))]:
        graph.add((subject, rdflib.URIRef((CORE if canonical else OLD) + name), value))
    return graph
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / 'baseline.py'
    path.write_bytes(subprocess.check_output(['git', '-C', str(ROOT), 'show', BASE + ':shantytown/shuttle_runs.py']))
    name = 'shantytown._baseline_shuttle_runs'
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    for label, source, expected in [('base', module, [1, 0]), ('candidate', shuttle_runs, [1, 1])]:
        results = [len(list(fixture(canonical).query(source._runs_sparql()))) for canonical in [False, True]]
        print(f'{label}: legacy rows={results[0]}, canonical rows={results[1]}', flush=True)
        assert results == expected
    print('PASS: canonical runs become visible and historical runs remain visible.')
