import tempfile, subprocess, socket, time, json, urllib.request, urllib.parse, os
from pathlib import Path
from shantytown.sd import SdTracker, StoreProof
from shantytown import seeds_plate, br, feed_check

binary = os.environ.get("SHANTYTOWN_TEST_QUIPU_SERVER")
G = "https://example.test/project/batch"
S = seeds_plate.SCHEMA
N = seeds_plate.SEEDS
import pytest


@pytest.mark.skipif(
    not binary, reason="set SHANTYTOWN_TEST_QUIPU_SERVER for isolated native fixture"
)
def test_native_roster_and_global_queue_batches(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="wu-ckp-native-") as d:
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        url = f"http://127.0.0.1:{port}"
        child = subprocess.Popen(
            [binary, "--db", d + "/q.db", "--bind", f"127.0.0.1:{port}"],
            cwd=d,
            env=dict(os.environ, HOME=d),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            for _ in range(100):
                try:
                    urllib.request.urlopen(url + "/health", timeout=1).close()
                    break
                except OSError:
                    time.sleep(0.1)
            facts = []
            for i in range(80):
                owner = f"agent{i%13}"
                status = "blocked" if i == 79 else "hooked" if i == 0 else "in_progress" if i < 13 else "open"
                sub = f"<{N}item/test-{i}>"
                props = [
                    ("a", f"<{S}Action>"),
                    (f"<{S}identifier>", json.dumps(f"test-{i}")),
                    (f"<{S}name>", json.dumps("actual work")),
                    (f"<{S}agent>", json.dumps(owner)),
                    (f"<{N}ontology/status>", json.dumps(status)),
                    (f"<{N}ontology/priority>", "1"),
                    (f"<{S}dateCreated>", json.dumps("2026-01-01T00:00:00Z")),
                ]
                facts.extend(f"{sub} {p} {o} ." for p, o in props)
            body = urllib.parse.urlencode(
                {
                    "update": "INSERT DATA { GRAPH <"
                    + G
                    + "> { "
                    + " ".join(facts)
                    + " } }"
                }
            ).encode()
            urllib.request.urlopen(
                urllib.request.Request(
                    url + "/update",
                    data=body,
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "X-Quipu-Client": "seeds",
                    },
                ),
                timeout=5,
            ).close()
            queries = []
            original = seeds_plate._query

            def counted(*a, **kw):
                queries.append(a[1])
                return original(*a, **kw)

            monkeypatch.setattr(seeds_plate, "_query", counted)

            def tracker():
                t = SdTracker(quipu=url, prefix="test")
                t.prove_store = lambda: StoreProof("fixture", None, url, "test", G)
                t._bd = lambda *a: (_ for _ in ()).throw(
                    AssertionError("SDK hydration")
                )
                return t

            t = tracker()
            t.render_shape_reads = seeds_plate.RenderShapeReads()
            read = br.plate_reader(
                t, require_complete=True, owners=[f"agent{i}" for i in range(13)]
            )
            for i in range(13):
                assert read(f"agent{i}").id == f"test-{i}"
            assert len(queries) <= 6, len(queries)
            print("roster native PASS", len(queries), "queries/13 exact held plates")
            # The render observes blocked capacity too, without allowing it
            # to replace held/ready assignments or rereading each owner.
            before_capacity = len(queries)
            for i in range(13):
                own = t.capacity_rows(f"agent{i}").exact()
                assert own and all(row["assignee"] == f"agent{i}" for row in own)
            assert len(queries) == before_capacity
            print("capacity native PASS", len(queries) - before_capacity, "additional queries/13 owners; blocked retained")
            assert "test-79" in {row["id"] for row in t.capacity_rows("agent1").exact()}
            assert "test-79" not in {row["id"] for row in t.plate_rows("agent1").exact()}
            assert sum(query.startswith("ASK") and "?bad" in query
                       for query in queries) == 1
            queries.clear()
            r, a = feed_check.queue_state(Path(d), None, tracker())
            assert len(a) == 12
            assert len(r) == 66
            assert len(queries) <= 4, len(queries)
            print("global queue native PASS", len(queries), "queries/66ready+12active")
            # A new observation sees deletion: the cache cannot outlive its reader.
            body = urllib.parse.urlencode(
                {
                    "update": f"DELETE WHERE {{ GRAPH <{G}> {{ <{N}item/test-0> ?p ?o }} }}"
                }
            ).encode()
            urllib.request.urlopen(
                urllib.request.Request(
                    url + "/update",
                    data=body,
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "X-Quipu-Client": "seeds",
                    },
                ),
                timeout=5,
            ).close()
            fresh = br.plate_reader(tracker(), require_complete=True, owners=["agent0"])
            assert fresh("agent0").id != "test-0"
            print("fresh observation deletion PASS")
            # Malformed held rows cannot vanish from the roster through the
            # status-first optimization, on either graph or owner spelling.
            def update(text):
                request = urllib.request.Request(
                    url + "/update", data=urllib.parse.urlencode({"update": text}).encode(),
                    headers={"Content-Type": "application/x-www-form-urlencoded",
                             "X-Quipu-Client": "seeds"})
                urllib.request.urlopen(request, timeout=5).close()
            for graph, owner in ((G, '"agent0"'),
                                 (G + "#seeds-ephemeral", f'<{N}principal/crew%2Fagent0>')):
                sub = f"<{N}item/malformed>"
                update(f"INSERT DATA {{ GRAPH <{graph}> {{ {sub} a <{S}Action> ; <{S}agent> {owner} . }} }}")
                assert not seeds_plate.owner_shape_supported(tracker().prove_store(), ("agent0",))
                update(f'INSERT DATA {{ GRAPH <{graph}> {{ {sub} <{N}ontology/status> "future" . }} }}')
                assert not seeds_plate.owner_shape_supported(tracker().prove_store(), ("agent0",))
                update(f'INSERT DATA {{ GRAPH <{graph}> {{ {sub} <{N}ontology/status> "closed" . }} }}')
                assert seeds_plate.owner_shape_supported(tracker().prove_store(), ("agent0",))
                update(f"DELETE WHERE {{ GRAPH <{graph}> {{ {sub} ?p ?o }} }}")
            print("missing/unknown status refusal and valid-state coexistence PASS")
            # The indexed plain-status guard must not turn non-plain statuses
            # into a supported shape, or reject a valid mixed-status row.
            for graph in (G, G + "#seeds-ephemeral"):
                sub = f"<{N}item/status-term-control>"
                for status in ('<urn:status:open>', '7', '"open"@en',
                               '"future"', '"open"',
                               '"open"^^<http://www.w3.org/2001/XMLSchema#string>'):
                    update(f'INSERT DATA {{ GRAPH <{graph}> {{ {sub} a <{S}Action> ; '
                           f'<{S}agent> "agent0" ; <{N}ontology/status> {status} . }} }}')
                    expected = status in ('"open"',
                        '"open"^^<http://www.w3.org/2001/XMLSchema#string>')
                    assert seeds_plate.owner_shape_supported(
                        tracker().prove_store(), ("agent0",)) is expected
                    update(f'INSERT DATA {{ GRAPH <{graph}> {{ {sub} '
                           f'<{N}ontology/status> "closed" . }} }}')
                    assert seeds_plate.owner_shape_supported(
                        tracker().prove_store(), ("agent0",))
                    update(f"DELETE WHERE {{ GRAPH <{graph}> {{ {sub} ?p ?o }} }}")
        finally:
            child.terminate()
            child.wait(timeout=10)
