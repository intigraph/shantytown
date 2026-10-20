# Daily metrics join

A read-only consumer of frozen request-day and graph projections. The test
fixture is synthetic; no live catalog admission or production acceptance is
claimed. See [design.md](design.md) for the source and execution contract.

For validated, explicitly scoped source projections, the consumer runs one
literal query over four disjoint token kinds and all 30 complete UTC days:

```sh
uv run --script consume.py --daily daily.json --closed closed.json \
  --identities identities.json --end-exclusive 2026-10-16
uv run --no-project --with duckdb==1.4.3 python -m unittest test_consume.py
```

`daily.json` is the optional st cost producer's request-day output. The identity
file is `{"schema_version":1,"agents":[{"label":"alpha","iri":"urn:example:agent:alpha"}]}`;
its canonical mappings must be independently verified, never guessed from labels.
The closed projection has `schema_version:1`,
`semantics:"retained_close_current_assignee"`, UTC `start`/`end_exclusive`,
`graph_visible:true`, `truncated:false`, `distinct_control` matching the unique
item count, a `source` object with `graph_iri`, immutable `query_sha256` and
timezone-qualified `captured_at`, and `rows` containing `item_iri`, `agent_iri`,
`closed_at`. These fields describe a separately verified complete scoped graph projection; setting
booleans in a file does not prove an authorized or complete graph acquisition.

The command reads bounded JSON, uses bound SQL inserts and disables external
SQL access and extension loading. Its literal query fetches no credentials or
network data. This local trusted-recipe proof does not establish OS isolation
of ambient process authority. It returns source-file
and query hashes and per-session capture times. It preserves unknown token
quantities and always reports usage-day completeness as false until a separately
verified census contract exists. Its observed totals are not a full-history
cost claim. The graph projection's complete empty groups may be zero, while
missing usage groups stay NULL. Different capture times do not form a globally
consistent transaction. The actual live 30-day oracle remains an acceptance gate.

The synthetic oracle covers 240 rows (30 days, two agents, four token kinds),
including a missing token quantity and observed zeroes. Missing usage stays
unknown. Ten malformed source/identity/coverage/provenance cases refuse before
SQL. Producer UTC boundaries, replay, corrections, conflicting session agents
and malformed caches are tested separately in `tests/test_cost_daily.py`.
