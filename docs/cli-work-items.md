# Work items, gates and cost

The commands under `st work` that change an item, hold it behind a gate or account for what it cost. This page is part of [the CLI reference](cli.md).

## Replacing work-item text

`st work item update ITEM --notes-file FILE` fills empty notes or verifies an
identical body. Seeds and br protect existing text from replacement. To replace
it deliberately, read back the item, preserve its evidence and use
`--notes-file FILE --replace-text`. The same option applies to
`--description-file`; it is refused without a text file. It affects only the
explicit update and does not weaken ordinary tracker or deferral writes.

On Seeds, `st work item show ITEM` includes its `revision` (unknown backends
report null). The native exact-item display reads the typed version in its
existing bounded observation, without a second request. Malformed or contradictory
native tokens refuse; missing tokens remain unknown. Carry the token into the edit:
`st work item update ITEM --notes-file FILE --replace-text --if-revision N`.
The token is passed unchanged through any admission reread. A stale edit refuses
and retains Seeds' structured conflict metadata; it never refreshes the token or
retries the write. An indeterminate Seeds outcome also retains its operation
identity and readback metadata, rather than truncating it into a generic error.
Guarded Seeds failures emit JSON on stderr with exit 4 (conflict) or 8
(indeterminate); bearer strings remain redacted. The option refuses every
non-update verb before it can write.
Independent fields still share one item revision: explicitly
reread and rebase even when another writer changed a different field. Other
backends refuse `--if-revision` rather than silently dropping the guard.

The command writes once and verifies the exact new text. A timeout or failed
read-back can follow a committed write: inspect the item before deciding on any
retry. `--dry-run` performs no write, even with explicit replacement.

## Close failure diagnostics

A failed `st work item close` emits a structured `CLOSE_FAILED` error with the
actual tracker backend, child exit code, stdout and stderr. An observe warning
does not replace a later blocker refusal or a JSON reason on stdout. Each output
channel is bearer-redacted first. Outputs longer than 2,048 characters retain
the first 768 and last 1,280 characters, with an omission marker. A nonzero child
outcome remains unproven: read back the
item before deciding whether to retry. The command never retries or changes the
principal, blocker checks or close reason to get past a failure.

`st work item close` refuses, before any write, an item whose
`agent_context.deploy_admission` phase is not terminal (`drained` or
`cancelled`), and an item whose agent context cannot be parsed. Closing the
item does not release the admission, so CD would keep refusing on a
"competing INFLIGHT operation". `deploy_admission.py cancel` will not cancel a
closed item either. Cancel a never-begun `planned` operation, or resolve it,
before closing.

## Tracker result envelopes

`st work item show ITEM --result-json` and the corresponding update, comment,
close, rescope and ack operations opt into `tracker-result/v1`. Legacy output
is unchanged. Check the process status and `ok`; failed reads have null `data`,
never a successful empty board.

The envelope includes a per-invocation operation ID, task, known graph, phase,
mutation outcome, exit code, safe error category and reconciliation advice.
INPUT and precondition READ failures prove this invocation did not submit.
SUBMIT timeouts and READBACK failures preserve UNKNOWN. Verified operations
report COMMITTED, including already satisfied state; this does not promise a
new transaction. Dry runs have NOT_APPLICABLE mutation outcome. The operation
ID correlates diagnostics and does not replace native idempotence or CAS.

Known SDK exit codes and categories survive wrapping. HTTP auth, policy and
timeout responses, missing input, malformed JSON, conflicts and indeterminate
commits remain distinct; unknown classifications remain UNKNOWN. Errors omit
raw server bodies, private arguments and credentials. Normal command admission
still applies; this option grants no authority or retry.

For ambiguous comments, the existing bounded exact readback can establish that
the original attempt landed; it never resubmits automatically. Missing or
unreadable evidence keeps UNKNOWN.

A non-null `recovery` preserves a recognized native write-operation witness,
provenance graph and exact item IDs. It excludes private field differences and
bodies. Use this persisted identity, when available, to reconcile the SDK write;
the new per-invocation operation ID is only a diagnostic correlation key.


Ready-work utilization counts and board triage exclude both `inbox:` and legacy
`mail:` title markers, including leading whitespace, using the plate message
predicate. An `inbox` label on a real work item does not exclude that work.
Native ready counts apply the title exclusion before fetching metadata, and
legacy ready-list utilization applies the same rule. Unreadable readiness
remains unknown rather than zero. Listing an inbox remains a pure read;
explicit ACK closes tracker pointers and the scheduled retention sweep retires
old pointers while preserving their records and verified related links.

## Request command attribution

Tracker reads declare a finite command source (`st-anchor`, `st-plate`,
`st-inbox`, `st-stop_policy`, `st-stop_event`, `st-haul`, `st-tend`,
`st-work`, or `st-other`) separately from the underlying SDK operation.
Nested stop hooks retain the outer command. These values contain no command
arguments or message text and are diagnostic declarations, not identities or
authorization. Server logging and reader coverage are required to use them in
a traffic census; sending the headers alone does not establish attribution.

## Technical gates and Steve asks

`st work defer ITEM bead --reason 'resume_when: closed:TARGET' --dependency-reason 'Required API/schema/artifact from TARGET'` requires a one-line technical dependency. Queue order belongs on the plate. The target inherits the waiting item's priority before the item is deferred; an unconfirmed priority write stops without replaying it. A Steve ask behind a lower-priority target requires Sattler's `--sattler-reason`, recorded with the deferral. Dry runs write nothing.

Declare `repo: NAME` and/or `epic: ID` on separate notes lines. Different or unknown scopes flag Sattler through the existing natural tend pass. The pass follows at most eight gate links and performs at most 25 additional exact metadata reads; unreadable/truncated/cyclic chains retain UNKNOWN or a cycle finding and never release work based on those findings. Stall events are delivered once per chain until resolution, with a persistent delivery ledger. No additional timer is installed.

For an original Steve ask, retain these notes using the normal exact item notes update:

```text
steve_quote: Exact requested work
steve_source: Original request reference
steve_ask_at: 2026-10-05T12:00:00Z
```

Use the original full UTC timestamp, never the item's creation/modification date. Optional `work_started_at: ...Z` records actual work start; an `in_progress` item also counts as started. After 72 hours without work the existing tend pass delivers one event to Sattler, then Hammond on the next still-unstarted pass. Failed deliveries stay pending. A quote without complete time/source gets one provenance-UNKNOWN notice to Sattler, without an age claim. Historical unannotated prose is not a registered ask; preserve and annotate its original provenance to track it.

## Gate backstop digests and verdict cooldown

The existing natural `st fleet tend` pass sends at most one gate-backstop digest
per recipient per pass. Sattler receives the selected stalled chains and pending
Steve asks together; a verified ask escalation to Hammond remains a later pass.
The 12-event and metadata-read budgets remain in force. Pending events and ask
stages advance only after confirmed digest delivery; failed or indeterminate
sends retain pending state without retrying within that pass.

To record a verdict on the waiting item, retain its existing notes and add:

```text
gate_verdict: Keep this gate: required API is still pending
gate_verdict_by: sattler
gate_verdict_at: 2026-10-13T22:00:00Z
```

These are declared item metadata, not authenticated actor identity. A nonempty
verdict attributed to Sattler with a valid timestamp suppresses new gate-backstop
notifications for that item for 24 hours. Future, absent, invalid, or differently
attributed timestamps do not arm the cooldown. Pending delivery and prior ask
stages remain recorded; normal eligibility resumes when the cooldown expires.
The verdict does not release an item, rewrite priorities, or clear its gate.

## Quiet CI and installation waits

Keep a CI wait `in_progress` and record one exact event in the item's notes:
`resume_when: ci-terminal:github/example/project@<full commit SHA>` (Forgejo
uses `forgejo`), or `resume_when: installed:bobbin>=0.1.0`. This is an active
wait with no defer date. Both the stop hook and the idle-haul sweep suppress
repeat delivery while the event is pending or its observation is UNKNOWN.
Terminal CI wakes the owner even when it failed or was cancelled; it does not
approve a merge. An unreadable observation keeps the wait quiet and logs UNKNOWN.
A lead can explicitly resume source work by removing/replacing the active marker;
retained history must not contain another active `resume_when:` marker.

The item remains visible as in-progress work to the board and governor. This
shape applies without guessing milestone labels or changing parent membership.
Ordinary `st work defer` still requires its existing event and backstop checks.
Open technical `blocks` edges also suppress native haul continuation; the next
fresh blocker observation restores eligibility after closure.

Overseer decisions use Seeds' `ask` item type. They carry `unblocks` (the linked
item or epic id), `default` (the fallback text), and `expires_at` (the decision
deadline). Create them with `sd create --type ask --unblocks ID --default TEXT
--expires-at RFC3339 TITLE`; list them explicitly with `sd list --type ask`.
They stay out of worker plates, hauls, capacity, reminders and ready counts even
without a legacy ASK title or decision label. Expiry records a deadline; it does
not execute the fallback. `st work item update ID --type ask --unblocks ID
--default TEXT --expires-at RFC3339` and exact item reads retain these fields.

## Per-bead costs

`st work cost <bead>` reads Camayoc's `session_usage/work_cost` retrieval method.
This command earns a separate slot because `--sync` publishes closure receipts
and metrics; `stats` remains an agent report. Counts are calculated only by
Camayoc, including response deduplication and compaction, and allocated using
paired session-local task declarations. Scope and UNKNOWN are shown explicitly.

Configure `<root>/cost.json` with `rig`, `tracker_repo`, `retrieve_script`,
`sources` (each has `agent`, `harness`, `path`) and a writable `metric_path`.
Optional `metrics_script` and `publish_script` point at Camayoc's installed
publication commands. Missing configuration returns UNKNOWN with exit 2.
No credentials belong in this JSON; the scheduled environment supplies them.

`st work cost --sync` serializes publication, writes absolute per-kind gauges, and
appends a content-addressed cost comment to closed items through the public
tracker CLI. A late flush creates a marked provisional revision. An indeterminate
comment write retains its exact body; two absent read-backs separated in time
are required before retry. A reopened item receives no closure comment.

The quantities are uncached input, cache-read input, cache-write input and output.
Reasoning is a subset of output. Unknown fields are omitted from metrics rather
than zeroed. Reconstructed allocations can decrease, so `st_bead_tokens_total`
is a gauge despite its requested name; do not apply `rate()` to it. The freshness
and coverage gauges must accompany any dashboard interpretation.

## Bounded active-session cost sampling

For a reviewed sampling population, set `sample_active_sources: true` in
`cost.json`. Only `st work cost --sync` rotates: one source per invocation, round-robin
by agent/session, requiring a live pane, a recent stats session and transcript
metadata matching that session and workspace. Display commands keep their
configured sources and never advance sampling. No capacity or token count is
inferred by source selection.

This population uses `cost-active-graph-state.*` and
`cost-active-rotation.json`, preserving the original pilot files. Both populations'
pending writes and request cooldowns block a new attempt. Camayoc's existing
snapshot/item/record/byte/request caps remain unchanged. A refused source advances
the rotation but is not manufactured into a sample.

After 20 distinct observed shapes, sync pauses publication and writes
`cost-active-review.json` with min/median/max dimensions. The normal producer
receipt publishes `review_due` on the twentieth observation. The report describes
the supplied session population, not proof of the fleet's tail distribution.
Completed-review ticks refresh native Camayoc status metrics without source or
graph access, so an intentional pause does not masquerade as a dead producer.
Completed sync ticks also refresh `st_bead_cost_sync_last_run_timestamp_seconds`
and `st_bead_cost_paused_for_review` (1 during review, 0 otherwise) through the
configured cost metrics publisher, including cooldown ticks. Review and cooldown
preserve cached cost gauges and their last-success timestamp; without a cached
sample, only heartbeat gauges are emitted. A failed push returns UNKNOWN.
Review must precede any new population or cap change.

`st work cost --review-window --json` describes the exact paused window without
running the parser or publisher. It shares the existing producer lock and binds
the samples, recorded source identities, snapshot ledger, cooldown and reviewed
budget envelope. Heartbeat timestamps do not change this identity. Missing,
ambiguous or changed evidence refuses acceptance.

After the actual resource reviewers accept that exact window, prepare a decision
JSON containing `schema_version: 1`, `window_sha256`, `decision: "accept"`,
`mode: "bounded-pilot"` (or explicitly reviewed `"bounded-continuous"`), `reviewer` and an `evidence_ref` to the ruling. The file
records the decision; it is not an authentication or authority grant.
`st work cost --accept-window SHA256 --decision-file FILE` validates and describes
the successor without changing state. Add `--execute` only through the normal
reviewed runtime path. A stale hash, busy lock, pending write, malformed decision,
symlink or existing preparation refuses; never delete a preparation to retry.

Execution archives the predecessor under `cost-review-generations/SHA256/`,
preserves the original files, lifetime counters, refusals, snapshot ledger and
cooldown, then atomically commits `cost-active-generation.json`. The successor
starts a new bounded audit window; no history is reset and no tokens are counted
or published by this operation. Caps and the default twenty-shape pause remain.
Pilot mode does **not** enable continuous publication. An explicit
`bounded-continuous` ruling instead authorizes subsequent in-envelope windows
under that same policy: the scheduler archives each completed 20-shape window
and advances a new generation under its existing lock. The inherited reviewer
and evidence reference identify the original policy, not a fresh human review.
Only the pointer-hashed manifest grants this mode; editing mutable budget history
cannot enable it. Every predecessor remains on disk, and the live rotation keeps
only the current window. Lifetime runs/maxima/refusals, cooldown, snapshot ledger
and uncertain-write guards remain intact. Camayoc still enforces one snapshot,
eight items, 1000 records and 4 MiB before networking. A completed window with an
out-of-envelope observation stays paused for explicit review. Source installation
alone never selects this policy or accepts a real pending window.

Read the review status after a
lost reply rather than replaying acceptance. A visible successor is evidence of
the transition, not evidence of a subsequent successful cost publication.
Before the first transition, source rollback can restore the previous release.
After a generation is selected, retain a generation-aware reader: older releases
ignore the pointer. Pause and reconcile publication through the normal operator
path before a rollback to such a release; never discard generation evidence.

Cost displays also report `cost_coverage`: completed and UNKNOWN-cost seed
counts, their share, the whole-session limit, and the cohort's scope. This
reuses the seed records already read for the command; it is not a board-wide
completed-seed census and adds no tracker queries. A missing or malformed
cohort remains UNKNOWN. A verified empty cohort has no percentage. Human
single-seed output prints the same limit and count/share.

Current policy accounts only for eligible whole sessions of at most eight
items. Oversized sources are refused, never estimated. Observed token groups
can still be useful partial evidence, but without an independent census across
every session and cycle they do not establish complete cost for a closed seed.
Partitioning is not enabled by this display change. Closure receipts and token
arithmetic retain their existing parser-owned contracts.

Active-source cost exposition carries the parser's agent, harness and session
identity in a comment, atomically with its counts. A compatible Camayoc metrics
publisher partitions token and coverage samples by rig/agent/harness/session,
while scheduler status remains at the rig level. Rotation then preserves other
sampled sessions, and a corrected session replaces only its own allocations.
Sum token gauges across session groups for a bead, for example
`sum by (rig, bead, model, harness, kind) (st_bead_tokens_total)`.
These are observed supplied-source totals, not guaranteed lifetime costs.
Each source retains its own last-success timestamp; heartbeat refresh does not
make its cached costs fresh. Install the source-aware publisher before enabling
the source marker. Graph publication and its existing caps are unaffected.
