# Exact-item query selectivity

The same item query runs against one synthetic local store, before and after
moving the target predicate filter outside its `GRAPH` pattern. Both reads must
return the same five metadata rows, including their multiplicity. A separate
absent-item control must return zero. The fixture contains two graphs and 250
unrelated items in each graph.

Install the repository's test extras in a development environment, select a
reviewed native Quipu executable, and run:

```sh
QUIPU_NATIVE_TEST_BIN=/path/to/qp python3 docs/demos/item-reader-query/demo.py
```

The baseline is commit `878f24ea0743f8e0a49e2f9f4fb98aa150a59aa0`.
The recording identifies the candidate commit. Query and fixture paths in the
displayed command are placeholders for disposable files; the responses and
timings come from actual native queries. No service, production store or
credential is used. The small-fixture timings do not predict production latency.

The small output/timing recording and readable output are retained beside this
caption with the source change. Playback requires downloading both files and
the util-linux `scriptreplay` command; inline playback is not assumed.

```sh
scriptreplay --log-out output.log --log-timing timing.log
```
