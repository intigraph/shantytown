# Tend consumes the graph-owned order

With the same two unowned READY items and the pickup flag enabled in an isolated
fixture, the actual base ranking sweep makes zero named-query reads. The candidate
sweep consumes the graph-order fixture once and logs `due` before `old`, with its
scope and read-only boundary. Neither sweep sends a notification or changes input.

The before source is `shantytown/ranking_check.py` at exact base
`d0e8899ae8bf8553637e9859baae6bb4bb918338`; the candidate is the commit containing
this demo. The recording prints the actual before/after ranking-source hashes.
The module and query controls separately execute the shipped SPARQL and actual
lean projection over the same native-schema RDF fixture, and test missing,
changed, duplicate, malformed and stale proofs, wrong store identity, query and
ledger failure, five-minute attempt pacing and preserved P0 notification keys.

From a checkout retaining that base object:

```sh
PYTHONPATH=. python3 docs/demos/backlog-tend-rank/demo.py
scriptreplay --log-out docs/demos/backlog-tend-rank/output.log \
  --log-timing docs/demos/backlog-tend-rank/timing.log
```

The small [output](output.log) and [timing](timing.log) files are retained with
the source. Download both for local `scriptreplay`; no inline player is claimed.
The demo uses a disposable local state directory and a fixture query response,
not the native Quipu engine or a production endpoint. It establishes source
behavior, not live parser/load acceptance, an installed consumer, dispatch
authority, global board ordering or the parent item's seven-day outcomes.
