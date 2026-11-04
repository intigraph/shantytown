# Owner need and semantic-only evaluation

Compare known base `023868ba` with functional source `336d9ce` using the
[same fixture reproducer](rank-semantic-only.py). An unassigned open P1 now
has a cited `needs_owner` flag, while a deferred P0 and open P2 stay outside
that rule. `reowner` still requires a positively observed down owner.

On the same 30 fixture items, the legacy combined path invokes rank-band
choices. Semantic-only evaluation invokes exactly the two permitted nouls
per item, including P0 cases: 60 nouls, zero rank-band choices. All model
answers and quarantine receipts are isolated fixtures. This demonstrates the
call boundary, not live model accuracy or installation.

[Output](rank-semantic-only.output), [timing](rank-semantic-only.timing).
Playback verified with util-linux scriptreplay:

```sh
scriptreplay --log-out rank-semantic-only.output --log-timing rank-semantic-only.timing
python3 rank-semantic-only.py --source /path/to/checkout
```

No live model, graph, assignment or lifecycle writes occur. The changed source
was subsequently merged with current main `8ee0f7ea` before its full-suite run.

The band fixtures also show a zero-blocker external label changing from
blocked to due with a visible stale-gate flag. A human gate remains blocked;
an unresolved prerequisite becomes UNKNOWN rather than a zero-blocker claim.
Every fixture keeps lifecycle changes disabled. Full-suite results are
reported separately; this recording proves only source behavior.

The adjudicated fixtures also cover an open/deferred P0 behind a proven
stale gate (immediate) and deliberately parked work with proven zero blockers
(later). A parked item with real blockers stays blocked. The rule applies
generically, including future-due P0 work; it is not fitted to individual IDs.
