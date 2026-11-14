# Declared duties held by a stopped owner

This is a replayable terminal recording of the library through the existing
fleet-tend sweep, using a synthetic registry, process observer and tracker.
It uses an isolated local inbox and never accesses a live board, process or
credential. It demonstrates source behavior, not installed fleet acceptance.

Base: `48bb2a84b566cf107214057c4a5e1d05a928080d`.
The recorded candidate's exact source bytes are bound by
[source.sha256](source.sha256); verify with `sha256sum -c` from the repository
root. The candidate is the source added by this PR, not a released version.

With the same stopped worker, supported queue, external reservation and ASK,
the base leaves the queue with the worker and files no repair or page. The
candidate hands the supported queue to the live eligible lead. Two passes
produce one external-reservation repair and one page. That reservation remains
orphaned until its actual external binding is repaired: the demo does not
claim a registry edit repairs it. ASK ownership remains intact. A stop without
explicit disposition refuses before its pane callback runs.

Read [the actual transcript](output.log). Download it with
[timing.log](timing.log) and replay using:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

This is a terminal recording, not an inline video. Both base and candidate runs
and the combined recording passed the HOME-escape guard. A repeat run needs
an isolated archive of the base, Python >=3.11 and the repository checkout:

```sh
DUTY_DEMO_BASE_SOURCE=/path/to/base-archive bash docs/demos/stranded-duties/run.sh
```

The small transcript, timing data and probe are retained here with the source.
Deployment, complete external-producer inventory, serving metrics/alerts,
backfill and a natural scheduled pass remain separate acceptance work.
