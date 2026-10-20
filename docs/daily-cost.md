# Daily usage projections

The cost producer can write a disposable daily projection alongside its existing
metrics with an explicit `daily_output` file path in its cost configuration.
This option is off by default. The output directory must already exist. The
existing cost lock serializes updates. No new schedule, transcript discovery,
parser, graph write or external dependency is introduced.

Camayoc remains the authority for harness request deduplication and disjoint
token quantities. The producer groups its returned `records` by **UTC request
day, agent, seed, harness and model**. Session snapshots replace prior snapshots:
replay does not add twice, and corrected attribution removes the old allocation.
A failed or conflicting source preserves the previous file. Unknown quantities
remain null and unattributed requests remain explicitly unattributed. The existing
corrective token gauge is never treated as a monotonic counter or daily usage.

The JSON includes source session identities, Camayoc receipts, capture times,
query semantics and scope. A 30-day retention window plus today bounds cached
rows. This is a disposable projection of supplied requests, not a second
source of truth or proof that every session/day was observed. Complete day
coverage needs an independently verified source census; current active-session
rotation cannot establish thirty days of fleet history. Consumers must preserve
that UNKNOWN, compare capture times and hashes, and bind canonical graph IRIs
through an explicit mapping. Cost label strings are not automatically IRIs.

A DuckDB consumer can project the frozen JSON's session rows into a table and
join them to complete retained-close cohorts from the graph. Current assignment
and retained close time are not the historical closing actor. No per-sample
triples are needed. Enabling the option, publishing metric definitions/catalog
recipes and granting source reads remain separately reviewed operations.

The [private join proof](probes/metrics-join/README.md) exercises a literal
DuckDB query over synthetic daily projections. It does not establish live
history, catalog admission or full day coverage.
