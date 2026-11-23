# Initial Python HTTP read budget

Three processes issue distinct native direct queries against one private
loopback HTTP fixture, with `ST_QUIPU_READS_PER_MINUTE=2`. Watch `http_queries`:
the base dispatches3 and returns3 populated answers; the candidate dispatches2,
returns2 populated answers and refuses the third before dispatch. Turning the
knob off then permits one additional populated direct query on both sources.

This is a **replayable source-fixture terminal recording** with actual loopback
HTTP requests. It uses no remote store, real SDK child or deployed configuration.
The source defaults the budget OFF. The demonstrated counter covers initial
Python dispatches only; SDK-internal HTTP, redirects and other cache/origin/UID
namespaces are outside this experiment.

- Base: `556417ebfb6f749f274b07212fec0996add948ec`.
- Candidate functional source: `b068c46ad6f37c6fbe40a302329338e672d27af2`.
- The actual native client source SHA256 is printed in the recording. The later
  artifact-only commit preserves the candidate runtime source.
- [Output recording / readable transcript](output.log), [timing](timing.log).
  These small sanitized files use the repository's existing `docs/demos` retention.

Download both and replay with util-linux `scriptreplay` (local replay verified):

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

To repeat from a candidate source root with pytest installed:

```sh
base_export=$(mktemp -d)
git archive 556417ebfb6f749f274b07212fec0996add948ec | tar -x -C "$base_export"
mkdir -p "$base_export/docs/demos/read-dispatch-budget"
cp docs/demos/read-dispatch-budget/demo.py "$base_export/docs/demos/read-dispatch-budget/"
DEMO_BASE_ROOT="$base_export" bash docs/demos/read-dispatch-budget/record.sh
```

Remove the disposable export afterward. The existing `test_seeds_read_cache`
fixture supplies the isolated HTTP service and private cache. This short recording
exercises admission and positive rollback, not a sixty-second production soak,
fleet-wide coverage or installed request-rate acceptance.
