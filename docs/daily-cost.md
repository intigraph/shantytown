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

The [private join proof](https://github.com/intigraph/shantytown/blob/main/docs/probes/metrics-join/README.md) exercises a literal
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
These are API-equivalent estimates at published rates, not invoices.

## Plan share

Flat plans have no per-token bill. With an explicit `plan_share` block in
`cost.json`, `st work cost ITEM` and the cost metrics add a **measured** plan
share for each declared focus interval:

```json
"plan_share": {
  "readings_file": "/path/to/account-window-readings.jsonl",
  "plans": {"acct-a": {"usd": 200, "period_days": 30,
                       "window": "seven_day", "window_days": 7}}
}
```

Each readings line is `{"account", "window", "ts", "pct", "resets_at"}`: the
deployment's own scrape of the account's window utilization (for Claude, the
series behind `claude_usage_utilization_pct`). Plan share is the account's
utilization points burned between the readings bracketing the focus, times the
plan's price for one window (`usd * window_days / period_days / 100` per point).
The denominator is the account's own meter, so no token census is assumed.

It is reported only when the measured interval is provably the item's alone.
Otherwise the interval is UNKNOWN, with its reason: the focus is still open; no
reading within 900 s brackets it; the window reset (or its reset time is
unknown) or utilization fell between readings; the agent's launch stamp
(`governor/account-launches/`) postdates the focus, so its account then is
unknown; another declared focus anywhere in the fleet overlaps the measured
interval on that account; any other agent is stamped on that account, or was
launched during the interval onto an account we cannot name; or the account has
no declared plan price. Account use outside st is invisible to this check, so
declare plans only for accounts dedicated to the crew.

`st_bead_plan_share_usd{rig,bead,agent,account,window,interval_start}` is
emitted only for measured intervals; an UNKNOWN interval has no sample, never a
zero. Display shows the known subtotal over measured/total intervals when any
interval is UNKNOWN. Without the block, Camayoc's `plan_share_reason` is shown
unchanged. Closure receipts are unaffected.

Codex display discovery includes the durable session directory used by harness
launches, matches the recorded workspace, and deduplicates symlinks. It does not
infer ownership from the newest filename. This expands supplied-source coverage;
it does not establish a complete historical source census.
