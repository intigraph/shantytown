# Metrics map and daily joins — review candidate

The graph catalogs metric definitions and access recipes. Prometheus retains samples. A bounded adapter freezes only the required 30 complete UTC days, and DuckDB joins that projection to a bounded, complete graph projection. Neither samples nor every query result become triples.

## First consumer contract

One row per canonical agent IRI and complete UTC day, with separately named token kinds and retained closed-item cohorts. Output includes source identifiers, query revisions, capture times, coverage, and hashes. A missing observation is NULL/UNKNOWN; an explicitly complete empty cohort is zero. Joining a current assignee to a retained close date means *currently assigned retained closures*, not *items closed by that actor*. A reopen may change this cohort. An audit of closing actors requires transition history and is a different input.

A reproducible 30-day answer needs a source that assigns actual usage to UTC event days. The discovered token metric is explicitly a **corrective gauge**: later allocations can decrease. `increase()` assumes counter resets; it is invalid for this series. Differencing its samples measures observed allocation changes, including revisions and task reassignment, and cannot reconstruct when tokens were consumed. Keep those quantities distinct. The initial live probe finds historical samples, but establishes neither uninterrupted coverage nor daily usage semantics. The chosen source is per-turn harness usage entries, parsed by the existing Camayoc accounting path and aggregated by the st cost producer into UTC day, agent and seed. The optional daily projection is off by default; source-set completeness and independent real-data verification remain required for authoritative tokens/day. No historical usage is backfilled by inventing zeroes or guessing reset boundaries.

## Catalog

Reuse the existing governed Metric type for metric definitions, including name, type, label schema, operational owner, unit, source locator and semantics. This existing type has a label-only shape: its governance does not validate the consumer execution contract. DCAT Dataset/Distribution/DataService and CSVW column descriptions remain the shared qhapaq design, not a competing local catalog model. The existing catalog profile still needs its compatibility correction and deliberate admission. Consumer manifests are private preparation artifacts until that path is reviewed; they do not grant arbitrary SQL, network or credential access.

A named query binds immutable SQL, projection schema, source scope, canonical identity-map revision, rights, time range, maximum bytes/rows, freshness and completeness. Metric label values are not automatically graph IRIs. Require an explicit one-to-one owner-reviewed agent mapping; preserve unknown mappings as a refusal. Work item identity must be the exact source IRI, not a title or a guessed prefix.

## Read path and isolation

Use a reviewed adapter for bounded Prometheus range/API projections or disposable Parquet, rather than ingesting samples into RDF. Pin the engine and extensions. An admitted production executor must receive only validated frozen projections and use separate OS-level restrictions for ambient credentials and network authority. This local proof executes reviewed literal SQL over in-memory typed inputs, disables external SQL access and extension auto-loading, and fetches no service credentials. It does not establish OS isolation or a general SQL service. Executing a catalog recipe still requires separate admission.

Capture the source request, response completeness, UTC boundaries, capture time, metric semantics and normalization revision with each projection. Validate duplicate identity/day/kind rows, finite nonnegative daily usage, malformed dates, bounds, conflicting aliases, input hashes and unknown schemas before running SQL. Retained item cohorts require a complete scoped graph response with positive graph visibility/control, no truncation, unique item identity, and explicit current-assignment semantics. Cross-source capture times are disclosed; no global transactional snapshot is claimed.

## Acceptance and gates

The private demonstration must produce the exact independent oracle across 30 days, including observed zero and missing coverage. Negative controls must refuse ambiguous gauge-as-usage input, mismatched identity and duplicate rows. Production acceptance remains the same documented command over eligible real source projections discovered through the governed map, followed by an independently checked result. The private result cannot discharge that gate. The existing map/profile review and eligible usage-day source are actual data-path dependencies; queue order is not one. No collector, catalog loading, new recording rule, runtime deployment or historical backfill is performed by this design.
