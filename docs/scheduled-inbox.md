# Fixed inbox child for signed scheduled delivery

`python -m shantytown.scheduled_inbox` supplies the child side of Chaski's
existing `FixedOutcomeExecutor` protocol. The runtime owner pins the complete
argv, environment, artifact, working directory and limits in the execution
manifest. Nothing in a graph notification selects a command or message.

Required arguments are `--root`, `--backend`, `--registry`, `--sender`,
`--recipient`, `--job` and `--message`. The root must be an existing absolute
deployment path. Backend and registry are explicit; there is no routing fallback.
`--sender` must match the fixed child's `SHANTY_AGENT`. `files` is available for
isolated fixtures; the production backend follows the admitted deployment.
The child inherits only the environment supplied by the outer executor; the
runtime owner must pin the normal store route and source environment there.

Use `ST_SCHEDULED_RESULT_FD` as the executor's `result_fd_env`. It must name a
writable pipe descriptor above standard input/output/error. Missing or invalid
channels refuse before delivery. The child invokes the real ST parser and
durable inbox command with an attributed `[job NAME]` message. This preserves
persist-first delivery, registry checks, pane submission, journal and host
routing. It never reads job TOML, scans work items, creates a timer or calls an
alternative message transport. Dispatch/go remains a separate future child;
this inbox pilot does not claim governor/triage execution of a work item.

Normal ST exit zero yields `succeeded` and exit zero in the bounded JSON result.
That means the pointer persisted: the recipient can be down or live submission
unverified. It does **not** mean the recipient performed a watch. An explicit
ST refusal yields `failed` and exit one. No refusal is relabeled as a hold.
Exit two, exceptions, invalid returns and lost result writes produce no terminal
receipt and exit two. A persistence request can commit before its reply is lost;
this child never retries, falls back or attempts to reconcile that uncertainty.

The surrounding Chaski receiver must first admit and durably claim the scoped
slot. It then records signed started/terminal state through Shuttle and accepts
only exact publication readback before acknowledging its outbox. On missing
child result it retains the claim as UNKNOWN; rollback must preserve the slot
ledger, emitter outbox and Shuttle run state. Do not rerun this child manually
to repair a missing receipt. Calling it directly is an ordinary inbox action,
not an independently signed or deduplicated scheduled run.

## First pilot contract and remaining gates

Reuse Chaski `226aba02` catalogue projection, incremental deadline/change
consumer, scheduled sink, durable receiver and fixed outcome executor; reuse
Shuttle `67ec0d10` signed port and history. ST `708b034` already supplies the
typed explicit-graph catalogue reader and normal inbox command. These are
measured source identities, not installed-version claims. No engine-domain
shape belongs in Quipu. Runtime job profiles/producer semantics belong in the
Camayoc software factory, using schema.org first and only reusable Quechua terms.

The only pilot is the existing Mac semantic-web watch addressed to its owner.
Harding's retained October 15 metadata reports Monday 09:17 America/New_York;
current declaration bytes, raw action body and current host identity remain
unverified. A fixed 604800-second period is not that calendar schedule across
DST. Preserve exact calendar semantics or use an explicitly admitted next
deadline with an owner for advancing it; the current fixed-interval catalogue
and projection cannot certify calendar recurrence. This bridge enables neither.

Before execution, Root must ACK the concrete same-SHA deployment and rollback
packet after current CI, installed artifact identity, scoped profile/query,
host mapping, key registration and existing-key smoke checks. Preserve the
separate Mac source-environment/backend-routing fix: a tmux global alone is not
a durable service configuration. Obtain the current job declaration from its
owner before enrollment. No source test authorizes enrollment, a service start,
key access, cron editing or early legacy deletion.

Acceptance requires same-job natural scheduled delivery and exact signed graph
readback, a positive natural control for missed-deadline reporting, a missed
deadline drill, duplicate/restart/rollback proof and before/after tend/read
measurements. Each watch run also needs its Quipu episode and a separate node
per finding linked to archives under the domain profile; a signed inbox nudge
alone does not satisfy that producer contract. Watches must derive queries
rather than rely on agent curation. Keep legacy pending/uncertain work until
reconciled, and prove single ownership before retiring evaluation/polling.

## Source proof

Run `python3 docs/demos/scheduled-inbox.py` in a source checkout. It launches
actual children against a temporary local FilesInbox, checks the persisted
attributed pointer, a refused recipient and a missing result channel. No graph,
key, service, scheduler or real recipient is contacted. The tests additionally
simulate a response lost after a real local commit: one pointer survives, no
receipt is emitted, and no retry occurs. This demonstrates source behavior,
not signed runtime acceptance or completion of the scheduled watch.
