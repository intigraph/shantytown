# Completed-anchor pickup

The input is an isolated worker queue: one owned P2 and one unowned ready P1,
after the current anchor ends. The existing own-queue selection feeds the P2;
the new library chooses the P1, verifies its observed revision through the
claim callback, and retains the P2. A refused graph read produces zero claims.

This recording uses the actual candidate-selection library with fixture graph
order, SDK claim and admission. It proves local selection, not a live graph
query, native mutation, deployment or worker preemption. The real stop-hook and
native capacity/CAS boundaries have separate tests. The before selection is
the `mine[0]` expression in base commit
`6bb4694988539c60fbc1a4060a9ecb75fe9c8bcf`; the after source is the commit
containing this demo. No source or input changed after recording.

From the repository root:

```sh
PYTHONPATH=. python3 docs/demos/backlog-pickup/demo.py
scriptreplay --log-out docs/demos/backlog-pickup/output.log \
  --log-timing docs/demos/backlog-pickup/timing.log
```

[Recorded output](output.log) and [timing](timing.log) form a small replayable
terminal recording, retained in Git with this feature. Playback was checked
with `scriptreplay`; no inline web player is promised. Download both files to
replay, or read the output as a transcript.
