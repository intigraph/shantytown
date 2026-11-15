# Resume goes back to ranked work

This is an offline library fixture, not a live tracker or installed acceptance.
The same resumed item is evaluated with the actual `TrackerAdapter.undefer`
method from base `c96be285f052ae5ec709137842240bea0b887ce1` and this candidate.
The tracker update is an in-memory fixture; ranking and haul readers are real.

Before: a resumed P1 stays owned by `worker` and self-feeds from that haul,
while the ready P0 is in the coordinator pool. After: both are in the ranked
pool, P0 first. The inverse shows a resumed P0 is still first and dispatchable.

Repeat from the repository root:

```sh
PYTHONPATH=. python3 docs/probes/resume-pool-ranking/demo.py
scriptreplay --log-out docs/probes/resume-pool-ranking/output.log --log-timing docs/probes/resume-pool-ranking/timing.log
```

The small output/timing recording is retained in Git alongside this caption;
it requires downloading and terminal replay. `output.log` is also the readable
transcript. Candidate identity is the PR commit containing this directory.
