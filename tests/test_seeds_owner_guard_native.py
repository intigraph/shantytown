"""Compare guard result bags on a real, isolated Quipu store."""
import collections
import json
import os
import socket
import subprocess
import time
import urllib.parse
import urllib.request
from types import SimpleNamespace

import pytest

from shantytown import seeds_plate as sp

G = "https://example.test/owner-guard"
S, N = sp.SCHEMA, sp.SEEDS
KNOWN = '("open", "hooked", "in_progress", "blocked", "deferred", "closed", "tombstone")'
BINARY = os.environ.get("SHANTYTOWN_TEST_QUIPU_SERVER")


def reference(proof, owner):
    """Previous existential guard, including its UNION bag multiplicity."""
    clauses = ([sp._feed_owner_clause(owner)] if isinstance(owner, tuple) else [
        f'?s <{S}agent> {term} . ' for name in dict.fromkeys((owner, owner.split('/')[-1]))
        for term in (json.dumps(name), sp._iri(N + 'principal/' + urllib.parse.quote(name, safe='')))
    ])
    if owner == ():
        clauses = []
    branches = []
    for graph in (proof.graph, proof.graph + "#seeds-ephemeral"):
        for clause in clauses:
            for guard in (
                f'?s <{N}ontology/status> ?bad . FILTER(?bad NOT IN {KNOWN}) '
                f'FILTER NOT EXISTS {{ ?s <{N}ontology/status> ?good . FILTER(?good IN {KNOWN}) }} ',
                f'FILTER NOT EXISTS {{ ?s <{N}ontology/status> ?any . '
                'FILTER(isLiteral(?any) && sameTerm(?any, STR(?any))) } ',
            ):
                branches.append(f'{{ GRAPH <{graph}> {{ {clause} '
                                f'FILTER EXISTS {{ ?s a <{S}Action> }} {guard} }} }}')
    return branches


@pytest.mark.skipif(not BINARY, reason="requires an isolated native Quipu fixture")
def test_absence_guard_preserves_bags_graphs_aliases_and_malformed_states(tmp_path):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    url = f"http://127.0.0.1:{port}"
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("QUIPU_", "SHANTY_", "SEEDS_", "ST_"))}
    env["HOME"] = str(tmp_path)
    with (tmp_path / "server.log").open("w") as log:
        child = subprocess.Popen([BINARY, "--db", str(tmp_path / "fixture.db"),
                                  "--bind", f"127.0.0.1:{port}"],
                                 cwd=tmp_path, env=env, stdout=log, stderr=log)
        try:
            for _ in range(100):
                try:
                    urllib.request.urlopen(url + "/health", timeout=1).close()
                    break
                except OSError:
                    time.sleep(.1)
            else:
                pytest.fail("native fixture did not start")

            def update(text):
                request = urllib.request.Request(url + "/update", data=urllib.parse.urlencode(
                    {"update": text}).encode(), headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "X-Quipu-Client": "seeds"})
                urllib.request.urlopen(request, timeout=10).close()

            profiles = []

            def read(branches, *, profile=False):
                if not branches:
                    return collections.Counter()
                query = "SELECT ?s WHERE { " + " UNION ".join(branches) + " }"
                request = urllib.request.Request(url + "/query", data=json.dumps(
                    {"query": query, "execution_profile": profile}).encode(),
                    headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(request, timeout=10) as response:
                    result = json.load(response)
                assert result.get("truncated") is False
                if profile:
                    profiles.append(result["execution_profile"])
                return collections.Counter(row["s"] for row in result["rows"])

            cases = {
                "missing": [], "unknown": ['"future"'], "plain": ['"open"'],
                "number": ['7'], "reference": ['<urn:open>'], "language": ['"open"@en'],
                "typed": ['"open"^^<http://www.w3.org/2001/XMLSchema#string>'],
                "mixed": ['"future"', '"closed"'],
                "mixed_nonplain": ['7', '"closed"'],
                "two_unknown": ['"future"', '"later"'],
            }
            for graph in (G, G + "#seeds-ephemeral"):
                facts = []
                for name, statuses in cases.items():
                    subject = f'<{graph}/{name}>'
                    facts.append(f'{subject} a <{S}Action> ; <{S}agent> "worker", '
                                 f'<{N}principal/crew%2Fworker>, "other" .')
                    facts.extend(f'{subject} <{N}ontology/status> {status} .' for status in statuses)
                # Inferred and duplicate types must not multiply the existential
                # guard, and an untyped subject must never become a refusal.
                facts += [f'<{graph}/child> a <urn:SubAction> ; <{S}agent> "worker" .',
                          f'<urn:SubAction> <http://www.w3.org/2000/01/rdf-schema#subClassOf> <{S}Action> .',
                          f'<{graph}/missing> a <urn:SubAction> .',
                          f'<{graph}/untyped> <{S}agent> "worker" .']
                update(f'INSERT DATA {{ GRAPH <{graph}> {{ {" ".join(facts)} }} }}')
            # A status in another graph cannot excuse a malformed owned row.
            update(f'INSERT DATA {{ GRAPH <urn:foreign> {{ <{G}/missing> '
                   f'<{N}ontology/status> "closed" . }} }}')
            proof = SimpleNamespace(graph=G)
            for owner in ("worker", "crew/worker", ("worker",),
                          ("worker", "worker", "other"), ("absent",), ()):
                expected = read(reference(proof, owner))
                actual = read(sp._unsupported_owner_branches(proof, owner))
                assert actual == expected, owner
                if owner == ("worker",):
                    assert actual[f"{G}/missing"] == 2  # two matching owner terms
                    assert actual[f"{G}/two_unknown"] == 4
                    assert not any(actual[f"{graph}/{name}"] for graph in
                                   (G, G + "#seeds-ephemeral") for name in
                                   ("plain", "typed", "mixed", "mixed_nonplain", "untyped"))
            # Incremental projection repair binds changed subjects inside each
            # GRAPH. A subquery must not leak unrelated malformed subjects.
            branches = sp._unsupported_owner_branches(proof, ("worker",))
            values = f'VALUES ?s {{ <{G}/missing> <{G}/two_unknown> }} '
            scoped = branches
            for graph in (G, G + "#seeds-ephemeral"):
                anchor = f'GRAPH <{graph}> {{ '
                scoped = [branch.replace(anchor, anchor + values) for branch in scoped]
            assert read(scoped) == collections.Counter({f"{G}/missing": 2,
                                                        f"{G}/two_unknown": 4})
            # The positive malformed guard disappears only after its own
            # scoped record is repaired, not because a foreign graph has it.
            update(f'INSERT DATA {{ GRAPH <{G}> {{ <{G}/missing> '
                   f'<{N}ontology/status> "closed" . }} }}')
            assert read(sp._unsupported_owner_branches(proof, ("worker",)))[f"{G}/missing"] == 0
            # Ordinary known-state rows must not trigger one type lookup each.
            # Compare native operator work, not wall time or compiler spelling.
            for start in range(0, 500, 100):
                facts = " ".join(
                    f'<urn:ordinary:{i}> a <{S}Action> ; <{S}agent> "worker" ; '
                    f'<{N}ontology/status> "closed" .' for i in range(start, start + 100))
                update(f'INSERT DATA {{ GRAPH <{G}> {{ {facts} }} }}')
            before = read(reference(proof, ("worker",)), profile=True)
            after = read(sp._unsupported_owner_branches(proof, ("worker",)), profile=True)
            assert before == after
            calls = [sum(op["calls"] for op in profile["operators"] if op["operator"] == "bgp")
                     for profile in profiles]
            print(f"same refusal bag; native BGP calls {calls[0]} -> {calls[1]}")
            assert calls[1] * 5 < calls[0], calls
        finally:
            child.terminate()
            child.wait(timeout=10)
