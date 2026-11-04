# Governed rank proposals

`st work triage --rank-proposals` reads the selected Seeds board's active and
deferred P0/P1 items and prints a proposed priority/rank/owner-state table. It
never updates priorities, ranks, assignees, holds or lifecycle state. Deferred
items remain deferred. An administrator accepts or edits each proposal using
the normal work-item tools and cites its policy evidence.

```sh
st work triage --rank-proposals --rank-rules reviewed-rules.json --dry-run
# Full provenance and UNKNOWN notes:
st work triage --rank-proposals --rank-rules reviewed-rules.json --rank-json --dry-run
```

A rule binding explicitly compiles an administrator-reviewed meaning onto an
exact graph IRI and text version. The reader requires a live Policy/Directive
type, provenance, matching SHA256 of its comment, and an unexpired review bound.
It does not interpret arbitrary prose or assume an old directive is still in
scope. A binding is a review declaration, not authentication or a global policy
promotion. Full live properties remain in the rules digest.

```json
[
  {
    "kind": "automation",
    "iri": "https://example.org/ontology/automation-priority",
    "text_sha256": "<64 lowercase hexadecimal characters>",
    "scope_ack": "Administrator reviewed this rule for the selected board",
    "valid_until": "2026-12-01T00:00:00Z",
    "fact_labels": ["work:automation"]
  }
]
```

Supported bindings are `merge-pr`, `automation`, `personal-need`, `dependency`
and `visible-hold`. Exact `work:merge-pr`, `work:automation` and `work:personal`
labels provide facts; title keywords never do. A binding may specify reviewed
`fact_labels` for merge/automation. Personal needs use their dated need rather
than a blanket low priority. Dependency priority flows toward prerequisites
present in the snapshot, with the path recorded; prerequisites outside P0/P1
remain explicit UNKNOWN findings. The command does not pretend that this scoped
snapshot proves the full board's dependency closure.

Ordering uses proposed priority, factual rank band (blocked/due/merge), exact
existing decimal rank, creation time and ID. New ranks are proposals over this
scope, not a reservation against concurrently changed work or outside ranks.
Re-owner flags require a positive host-scoped down observation. Missing hosts,
missing panes, failed peer reads and contradictory observations remain UNKNOWN;
retired owners remain held. A zero confirmed-down count with UNKNOWN owners does
not establish that every owner is running.

The dependency projection proves each candidate's identity and status even when
its edge set is empty. A failed, shadowed, stale or capped projection refuses
instead of silently filling empty lists. It reads native `blockedOn` edges, not
related or parent links, and does not hydrate retained import payloads.

## Frozen benchmark

`--benchmark cases.jsonl` uses at least 30 distinct, independently judged items.
Each JSONL entry contains a `before` item snapshot, optional prerequisite
`context` snapshots, `observed_at`, historical `owner_states`, a source-linked
`owner_evidence`, the ruling `source`, cited `rules`, and
`expected: {"priority": 0, "band": "normal", "reowner": false}`. The before row
includes id, title, description, status, priority, assignee, labels, blocked_by,
rank and dated fields as available. Historical owner evidence and the historical
clock are used, rather than today's crew liveness. Expected labels and ruling
text never enter model features. The whole cohort is validated before a call.

Reports include per-rule counts/agreement, the deterministic baseline, incremental
agreement, abstention/confidence splits and false-reowner
numerator/denominator. A zero-negative cohort reports an unknown rate. Existing
routing-assignee labels are not a substitute for human ranking judgments.

A Jev benchmark can add `--jev-command '<installed Jev MCP command>'`,
`--rank-inferred-graph '<existing plane namespace>/crew/inferred'` and
`--rank-journal-dir '<private owned directory>'`. Calls use the existing typed
Jev client and a none-of-these option; a shared 100-call budget bounds the run.
Only unresolved rank bands and automation/personal classification flags reach
the model. Exact facts decide first. Nouls remain probabilities and conditional
P0 candidates marked unaccepted; they never become observed facts or an
automatic priority, owner, dependency or lifecycle change. Every valid answer is archived as
an inferred Artifact, with request/model/confidence and a locally derived
request digest (not an invented external request ID). The writer checks the
live graph registry's committed/local/knowledge/low-trust labels and served
Artifact vocabulary before model calls. It never creates or relabels a plane.

The exact write body is fsynced to an owner-only journal before one `/knot`
request. Success requires a SHACL receipt and exact readback in that same graph.
Refusal, timeout, a repeated journal or unknown readback stops; there is no
resend, ROOT fallback, promotion or automatic undefer. Retain uncertain journals
for explicit reconciliation. The record is the model's answer artifact, not an
accepted decision or asserted truth about the item.

Live Jev ranking over the board requires `--rank-benchmark-report report.json`
and `--rank-admission admission.json`, plus the same explicit quarantine graph
and journal options. Admission contains the exact canonical `benchmark_digest`,
`accepted_by`, ruling IRI, `valid_until`, `minimum_model_cases`,
`minimum_agreement` and `maximum_false_reowner_rate`. These are explicit human
review declarations, not authenticated identities or automatic policy promotion.
The optional `flag_bounds` maps each accepted semantic arm (`automation`,
`personal-need`) to explicit `minimum_cases` and `maximum_brier` bounds. Its
benchmark labels use an optional `expected.flags` boolean map, never model
features. Reports retain per-arm labelled MODEL counts and Brier scores; absent
labels remain UNKNOWN. Observed label facts cannot qualify an untested model
arm, and an accepted rank band does not implicitly admit semantic flags. No
flag calls are made in normal mode without their own accepted calibration.
`minimum_model_cases` counts rank-choice cases, not extra noul calls.

The tool supplies no default thresholds and accepts no changed report, rule
version or model. A changed model's answer is quarantined and then refused.
Normal live proposals have a 1000-call budget; the benchmark's budget is 100.

Without an independently measured report and administrator ruling, deterministic
previews and benchmark preparation remain available; live Jev ranking refuses.
The tool does not supply its own labels, set a trust threshold from its test
fixtures or declare acceptance.
