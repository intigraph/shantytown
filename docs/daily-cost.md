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

## API-equivalent prices

When Camayoc supplies a `costs` projection, `st work cost ITEM` displays the
exact model, attribution basis, priced-token coverage and price-catalogue hash.
Missing prices remain UNKNOWN; the known subtotal is explicitly partial.
Closure receipts continue to contain declared token evidence only.

Prometheus receives `st_bead_api_equivalent_usd` only for a fully priced group,
`st_bead_api_equivalent_known_usd` for its known subtotal when at least one
request was priced, and `st_bead_priced_token_share` for pricing coverage.
All three carry the catalogue SHA-256 and attribution basis. A pricing-coverage
value of zero is not a zero-dollar observation. Install Camayoc's companion
source-aware publisher before enabling these samples.

Daily rows join Camayoc's prices by exact harness/session/agent/request ID and
retain the catalogue hash, known subtotal and priced-request count. A missing
price leaves the complete daily dollar total unknown while preserving tokens.
Session correction still replaces its prior rows rather than adding them.
These are API-equivalent estimates at published rates, not invoices. Plan share
stays unknown until measured account-window allocation is available.

Codex display discovery includes the durable session directory used by harness
launches, matches the recorded workspace, and deduplicates symlinks. It does not
infer ownership from the newest filename. This expands supplied-source coverage;
it does not establish a complete historical source census.
