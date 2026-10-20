# Select an owner's statuses in four branches

Run `PYTHONPATH=. python docs/probes/pr-demos/owner-status-filter/probe.py`
from the checkout with `quipu-server` on PATH (or set `QUIPU_SERVER_BIN`).
The probe loads the baseline implementation from commit `f00120e4`, captures
both implementations' actual generated decision queries, and compares them on
a disposable loopback Quipu fixture. Both must return the exact expected
subject/graph multiset and headers. The fixture includes both owner spellings,
both graphs, modern and legacy messages, wrong types, foreign owners and graphs,
and closed items. The process stops before exit.

The change retains constant owner terms and combines statuses with `FILTER IN`:
16 selection branches become 4. Feed and roster query forms stay unchanged.
Shape checks, field hydration, completeness, ambiguity and candidate caps remain
in the normal reader; this focused demonstration bypasses the shape check to
isolate candidate selection. The test suite covers those checks separately.

This demonstrates query shape and selection correctness, not production latency
or fleet query-rate acceptance. It adds no cache or timeout change.

Recorded native result: **16 branches / 6051 bytes → 4 branches / 1855 bytes**,
with the same 20 expected rows and headers. Replay `scriptreplay -t timing.log
output.log` from this directory. Byte counts apply to this fixture owner and graph.
