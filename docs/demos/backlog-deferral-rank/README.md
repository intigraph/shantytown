# Observed deferrals in graph-owned ranking

The same disposable fixture is written by the native Seeds counter implementation
from PR254 and queried with the exact shipped SPARQL templates. The unchanged v1
query selects the older item first. The candidate v2 query selects the item with
four observed deferral commits first; the other item's historical count remains
`UNKNOWN`. The real bounded consumer verifies SDK revision, priority, status,
owner and dates, returns the same immutable input rows, and performs no dispatch.

Base query: Shantytown `5e5057dde583169d611d02956d80604c3c9cef88`.
Candidate implementation: the exact PR head is recorded in the PR body. Native
fixture writer: Seeds implementation `3e9fb1fe0e0248946cf0317c7bd6b8af9b5e5005`,
merged through PR254 as `4cf5b2f5ddb6d8e8473dd9f19c5ad2ec48a11764`.
The query engine here is local RDFLib, **not** a live Quipu server or production
board. The N-Triples parser preserves the native writer's literal spelling;
RDFLib date normalization is disabled only while parsing the private export.
No production store, registry, consumer setting or operation is changed.

[Recording output](output.log), [timing](timing.log) and
[reproducer](demo.py) are retained with this source. Download both recording
files and replay with:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

Repeat with a counter-capable native Seeds binary:

```sh
python3 demo.py /absolute/path/to/sd
```

The signal is a lower bound from the observing writer protocol, not reconstructed
history or a total across old writers. Missing metadata never means zero. The
ranking contribution is capped at 64 and follows declared priority, due dates
and directive preference. Malformed/partial/future observations and conflicting
functional facts make query coverage incomplete, which refuses pickup. This does
not introduce dependency priority promotion, preempt active work, cull items, or
relax existing claim/governor/capacity checks.

Rollout dependency: register the separately pinned `seeds_work_rank_v2` through
its reviewed carrier before enabling the existing OFF pickup switch. v1 is
preserved; there is no fallback to a different query on missing/invalid v2 proof.
Installed acceptance and the seven-day backlog outcomes remain separate gates.
