# Caller revision guard

The installed CLI has no revision option. The candidate carries a caller's
revision unchanged into Seeds. In this recording, two readers start at revision
1. The first writer reaches revision 2. The adapter refuses the stale revision,
retains structured conflict details and preserves the first writer's text.
An explicit reread/rebase succeeds once and reaches revision 3.

Source base: `8ee0f7eaa1bd453838e2a4df69a5eea83673449e`.
Demonstrated candidate: `6eea9cf` (adapter implementation `865d2ed`).
The conflict/rebase scenario remains unchanged by the subsequent retention of
indeterminate-operation metadata; that branch has a separate fault control.
The candidate uses an isolated local Seeds fixture and the Python work-item API;
it is not an installed-service demonstration. The native remote display's typed
revision read is covered separately by its same-observation positive/refusal
controls. The copied candidate Seeds executable has SHA256
`bdcabd9f84db2e71862d9d39b42c7d3b244eee15db7521857d194ed0bce6361c`.

[Output recording](work-item-revision.log) and
[timing data](work-item-revision.timing) are a replayable terminal pair, not a
video or an inline player. Playback was checked with:

```sh
scriptreplay --log-out docs/pr-demos/work-item-revision.log \
  --log-timing docs/pr-demos/work-item-revision.timing
```

Repeat from this checkout with a built candidate `sd`:

```sh
ST_DEMO_SD=/path/to/candidate/sd PYTHONPATH=. \
  python3 docs/pr-demos/work-item-revision.py
```

The small output/timing pair is retained in Git with this caption. No live board
writes or credentials are part of the recording. CI, independent review and
normal installation remain separate requirements.
