# Messages, memory and history

`st inbox`, `st work directive` and `st agent memory`: what is delivered, what is kept and what is archived. This page is part of [the CLI reference](cli.md).

## `st work directive` — operator messages, captured by st (aegis-za4f.20)

Directive capture used to depend on someone remembering, and on the night it
mattered six directives were relayed to a lead to record, with wrong times. st
now records them itself:

- The administrator's `UserPromptSubmit` hook captures every prompt the operator
  types, and `st inbox` captures a message whose sender is `SHANTY_OPERATOR`.
  Text st delivered itself (the `[from x]` attribution prefix) is crew traffic
  and is not captured.
- Each message is ONE `a:OperatorMessage` node: its text (`rdfs:comment`),
  `a:receivedAt` (exact UTC, `xsd:dateTime`), `a:recipient`, `a:sessionId`,
  `a:sourceChannel` (`pane-prompt` or `inbox`) and `a:sourceKind`, written
  through the same governed `/knot` path the registry uses, so a SHACL refusal
  is a failure, not a success.
- `a:sourceKind` is `"operator-verbatim"` for a pane prompt and for an `st inbox`
  send whose sender `authenticated_actor()` proves is the operator. A sender
  known only from `$SHANTY_AGENT` (no identity policy, or no `TMUX_PANE` to
  check) is `"operator-claimed"`: any agent shell can set that variable. A
  relayed off-host send reaches the far side by `$SHANTY_AGENT`, so it is
  operator-claimed there.
- The spool keeps the raw text. The graph copy is the text after the shared
  secret masker (`jobs.mask_secrets`, the one job failure tails use); when it
  masked anything the node also carries `a:textRedacted true`.
- The local spool (`<root>/operator-messages/`) is written first. Its key is
  `om-<UTC>-<sha256 prefix>`: receive timestamp plus content hash. The same
  `st inbox` text to the same recipient within 10 minutes of a spooled copy is
  a redelivery and writes no second node; its receive time is appended to the
  prior record's `redelivered_at`, so nothing that arrived is dropped. A pane prompt is never deduped: the hook
  fires once per prompt, so typing "go" twice is two records (identical prompts
  in one second take a `-2`, `-3` key suffix). A hook with `SHANTY_AGENT` unset
  still spools, with no `a:recipient`; a corrupt spool file is skipped and
  reported UNKNOWN, never deleted. The hook and `st inbox` never wait on
  Quipu: they spool and hand the write to a detached flush. A failed write leaves
  the statement owed and the text on disk; `st work directive flush` retries
  idempotently.
- An off-host `st inbox` send is captured by the receiving host's own `st inbox`
  (the relay), not by the sender as well.
- Known gaps: a pane injection st does not prefix with `[from ...]` reads as the
  operator typing and is captured; a Codex administrator has no prompt hook, so
  only its `st inbox` path captures.
- Not every message is a directive. `st work directive mark <key>` confirms one (it
  adds `a:Directive`); `st work directive dismiss <key>` records that it is not
  one, which clears it from the review notice and keeps the node in Quipu.
  Dismissing a confirmed Directive is refused. `st work directive track <key> <seed>` or
  `st task "..." --directive <key|IRI>` confirms it and writes
  `a:trackedBy a:<seed>`. `--directive` takes only an st-captured `om-...` key
  (or an IRI ending in one) and is refused before the seed is created
  otherwise; a Directive minted by hand in Quipu has no spool record and gets
  its `trackedBy` through the governed write path directly. A link that is
  refused after creation exits REFUSED, one still owed to Quipu CANNOT_TELL.
- The administrator's `st anchor` lists messages to review, directives with no
  seed after `SHANTY_DIRECTIVE_TRACK_MINUTES`, and spooled writes still owed.
  `st work directive` (`list`) prints all of it.

## `st inbox` — a message, and somewhere for it to land

A Codex pane on the task list/new-task composer refuses live delivery: submitting
there creates a parallel task instead of messaging the running one. Open the
intended task first, or use `st inbox -d`; the durable message remains unread in
the inbox when the live nudge is refused. `st agent input` reports `TASK-LIST`
and refuses clear/dismiss on that screen. It does not pass launch/cycle readiness.
The running-task count is unknown from this footer alone.

In a deployment with a declared host and graph authority, an absent local recipient
card falls through to the graph for an **off-host** member. No shadow local card is
needed. Ephemeral delivery uses the declared host peer; durable delivery uses the
selected inbox backend and never types into a coincidentally named local pane.
If the graph is unreachable or times out, an ephemeral send tries the files
registry: first this host's projected cards, then the declared peers' local crew
snapshots over SSH. A successful fallback is named in the warning output. The
peer census must be complete and name exactly one owner; an unavailable peer,
missing recipient, or ambiguous ownership remains an unknown lookup with nothing
sent. No shadow card is written. A graph protocol/query error does not trigger
this fallback. Durable delivery keeps its existing lookup and persistence rules.
Sender pane ownership remains a local check even with `--registry quipu`, and the
receiving host resolves delivery through its own files registry.

```
st inbox ian "go read st-1"          send: straight into ian's pane (send-keys)
st inbox -d ian "HANDOFF: qdal.2"    durable: into ian's INBOX, then a live send
st inbox                             read: what is unread, for me. Marks nothing.
st inbox --count                     one integer, for a status bar. Marks nothing.
st inbox --read                      ACK: mark up to 15 unread messages read; repeat to drain
st inbox --read-id aegis-abc12       ACK only one absorbed message (repeatable)
```

A keyed durable broadcast is available for a bounded, explicit recipient list:

```bash
st inbox broadcast --to alice --to bob --delivery-key rollout-notice-1 --json "see the rollout item"
```

This persists **only**: it sends no live nudge, marks no pointer read and claims
no pane submission. Use the ordinary single-recipient command when live delivery
is required, and retain its reported confirmation limits. Broadcast verifies all
recipient identities first, then attempts each independently (at most 64 distinct
names). JSON returns the operation key and a per-recipient `persisted`, `refused`
or `UNKNOWN` result, with exact receipt IDs for confirmed persistence. It is not
an atomic all-recipient transaction; partial results return exit 2.

Keep the same explicit delivery key when resuming the same operation. A key is
1–128 ASCII characters: an initial letter/digit followed by letters/digits or
`_.:-`. On Seeds, the existing native
`--workflow-run` / `--step` / `--visit` create contract derives the stable receipt;
Shantytown does not guess its ID. Seeds reads that exact receipt back and verifies
its title and recipient. A reused key with changed content refuses, including
after the original pointer was acknowledged; it cannot reopen or overwrite it.
The files backend also supports stable keys with locked, atomic publication.
Other tracker adapters without this optional capability refuse keyed broadcasts
rather than fall back to a different store or an unkeyed create.

Ordinary Seeds durable sends also use a fresh operation key internally. Only a
native CAS-conflict exit (4) is retried, with the same complete create arguments,
up to 16 attempts with jitter. This handles different recipients contending on
the same tracker. Timeouts, exit 8, malformed replies, readback failures and other
refusals stop without an automatic resend. `UNKNOWN` can follow a committed write:
inspect the native outcome before resuming, retain the operation key, and never
invent a new key merely to hide uncertainty. Per-attempt SDK timeouts remain in
force; this is not a total broadcast latency guarantee.

When a durable message is successfully submitted to a live pane, `st` closes only
that message's pointer after confirming the input is not stranded. The closed bead
retains its content and history. If the recipient is down, the send fails, the input
is stranded, or pointer closure fails, the pointer remains open for `st inbox`.

Codex delivery first confirms an empty composer, or recognizes an explicit resend
of the exact body already stranded there. The latter retries Enter without
retyping the body, after the older turn ends and Codex identity is confirmed.
Clipped or ambiguous input is
unverified before typing. It waits 500 ms between the final literal chunk and Enter, then
checks for a new active turn with a cleared composer. A visible queue preview
is **not delivery**: Codex may hold it until a later tool boundary. Existing
activity alone is not confirmation. If the
composer still contains exactly the rendered message, the transport may retry
Enter once after the older turn ends and a fresh foreground check positively
identifies Codex (including Node with a live Codex launch identity). An unknown
or different foreground cannot authorize the retry. It never resends the body or submits a
different buffer. A clipped capture, unrelated input, or missing confirmation
reports `UNVERIFIED`. Ephemeral sends and dispatch return exit 2; dispatch does
not record an assignment. Durable sends retain the persisted inbox pointer and
return success for persistence while explicitly reporting unverified live
submission. Inspect the pane or read that pointer rather than blindly resending.

With a deployment root, Codex sends first retain the full body in a private
`delivery/send-<id>.json` record (directory 0700, records 0600), bound to the
declared tmux socket, pane, observed session creation time and process generation. If custody cannot
be written, nothing is typed. After the single submission retry fails, st can
clear its exact visible typed body, including multiline text, in an idle, positively
identified Codex session. It rechecks ownership, session and process identity before
each editing key and verifies an empty composer afterward. Cleanup uses bounded
line editing, never Escape or submission keys, and does not change the UNVERIFIED
send result. Busy, changed, opaque paste placeholders, clipped, ghost,
attribute-stripped and unknown input authorize no automatic clear. A later sender can clear the same owned failed
notice before submitting its own message; the older body remains retained.
Claude and explicit shell-launch sends keep their existing transport.

The existing scheduled `st fleet tend` pass supervises these records. It reuses
an existing durable inbox row, or creates one normal pointer to the retained
body. An uncertain inbox write is never blindly repeated. A cleared notice gets
at most one automatic redelivery in the same session; queued input is never
resent. An explicit inbox acknowledgment is distinct from terminal delivery.
Legacy inbox rows without custody may trigger an alert but never authorize
editing somebody's composer.

Accepted Codex queued input remains pending while a turn is busy; it is not a
failed submission, and pointers stay retained. Both the older “Messages to be
submitted after next tool call” and newer “Queued follow-up inputs” chrome are
recognized. If tend observes a queue still visible with an idle composer, it
immediately persists the existing `delivery-stalled` event to the lead/admin
and attempts one coordinator wake. A clipped preview cannot authorize submitting
an entire queue, so no Enter is sent and its unread pointer stays open. Any
visible queue prevents falsely retiring custody as dequeued. The same event
latches for the continuing backlog, avoiding repeated wakes.

For other unresolved input, the backlog timer starts after
tend observes idle input and resets on a busy or unreadable/no-box observation.
After 300 seconds unresolved while observed idle, the next tend observation persists
one `delivery-stalled` event to the configured lead/admin and attempts one
normal coordinator wake. An absolute one-hour ceiling from the first unresolved
observation also alarms regardless of pane state, including a perpetually busy
pane or an absent/unknown composer. Those composer states cannot establish idle
or busy. The event includes the elapsed backlog age, input classification and busy state,
not the message body. A continuing backlog does not generate another event,
even after its first event was drained. An empty backlog rearms detection.
For legacy rows, age starts at the first observation; it is not a guessed row
creation time. A working tend schedule is required: the threshold is not a
promise to deliver an alert while supervision itself is stopped. Persistence,
queued wake, actual receiver arrival and recovery remain separate facts.

An **off-host** durable recipient is nudged through the same declared peer the
ephemeral relay (and `st go`) uses: the peer host's own `st inbox` over SSH. A
relay that exits 0 counts as live delivery and closes the pointer. When no nudge
is possible — no `[host.peers.<host>]`, SSH failure, timeout, or the peer
refusing the live send — the report says `off-host: not nudged (<why>)` and the
pointer stays open. It never says "recipient not live" for an agent on another
host: that sentence claims a pane was looked at, and none was (aegis-az0a40).
The exit code is 0 in every case once the durable persist succeeded, as before.

For pointers that survive because delivery was offline or uncertain, acknowledgment
can be selective: repeat `--read-id ID` for messages already absorbed while leaving
an open question unread. The command preflights every ID and changes nothing if any
named ID is not currently unread for that recipient.

`--read` acknowledges at most 15 messages from its initial unread snapshot per
invocation. It prints and flushes each body before closing that receipt, then
prints progress for each independent close. Repeat the command to continue when
it reports unattempted snapshot messages; new arrivals remain for a later read.
This bounds the default batch size, not the duration of a remote operation.
Acknowledgments are not atomic: an interrupted command can leave earlier messages
read. Their bodies have already been printed. An uncertain close returns exit 2
and names the receipt as `UNCONFIRMED`; inspect the inbox before continuing.
Explicit `--read-id` selections retain their whole-selection preflight and are
not truncated to 15. `--dry-run` reports the selection and performs no closes.

`st agent new` (including the shared relaunch path used by start, attach, and cycle) now
drains that offline case without turning startup into an acknowledgment. After the
runtime and its hooks are verified, the launcher snapshots the recipient's unread
messages and injects one marked startup-context block. It closes exactly those IDs
when Codex returns an exact-body first-turn receipt. Other adapters require a
scrollback read-back containing the complete end marker without stranded input.
A Codex marker echo without that receipt does not acknowledge anything; a marker
that scrolls away after a confirmed turn does not invalidate its receipt. A failed
send, missing required evidence, unreadable inbox or aborted startup preserves
unacknowledged pointers. Plain list and `--count` remain pure reads;
age is never treated as evidence of delivery.

The default send is unchanged and is still one line of `tmux send-keys`. What is new is the **type**.

The old `mail -d` persisted a message as an ordinary tracker item assigned to the recipient, and then
**nothing ever read it back** — the sender was told "they'll pick it up on their next prime", which
was not true, and the item landed on the recipient's **plate**, which holds exactly one thing. So a
message did not merely fail to arrive; it *evicted the agent's actual work*. Both halves are the same
mistake: a message is not a work item, and it needs its own read side.

So there is an `Inbox` protocol (`shantytown/inbox.py`) with three methods and two implementations:

| | |
|---|---|
| `deliver(to, body, frm)` | the write. On the store before it is read, so a recipient who is down still gets it. |
| `unread(me)` | the **pure read**. Marks nothing. `--count` is `len()` of this. |
| `mark_read(me, ids)` | the ack, separate and explicit. `--read` is the only thing that calls it. |

Selected by the **same `--backend` switch as the tracker** — one switch, or you send on one backend
and read on another. `files` gives a store beside `events/` (structurally off the plate: no plate
reader globs that directory). `beads` maps a message onto a real bead — `inbox: <body>`, assigned to
the recipient, labelled `inbox`, closed when read — which is Stiwi's ask verbatim: *"an inbox concept
we can map to beads or other ticket modules."* On that backend the exclusion cannot be structural, so
`inbox.is_message()` is the one predicate both plate readers use, and it excludes the legacy `mail:`
prefix too — those items are open and assigned on the live store right now.

There is still no bus: no queue, no threads, no routing, no retry, no daemon. Three methods.

## Explicit routine progress for scoped administrator budgets

`st inbox -d --routine <agent> <pointer>` declares batchable progress. Use it only
when no immediate decision, blocked-work response, ownership handoff, or active
window coordination is needed. Operator messages, urgent controls, governance
notifications, gate/decision requests and handoffs use the unchanged immediate
path. These are declared exemptions, not authenticated identity or urgency inferred
from body text. Omitting `--routine` always preserves existing delivery behavior.

Only an explicitly named administrator using Claude, with ENFORCE enabled and a
fresh quota/cadence observation, can defer the routine live nudge. The durable
message is persisted first and stays unread. The existing `fleet tend` pass
submits one batch after the original cadence deadline (at most 900 seconds) plus
its next actual scheduled tick. OFF, unknown evidence or clock reversal releases
early. No new daemon/timer is installed, no off-host relay is delayed, and a dry
run neither persists nor sends. This does not bound ongoing-turn or account spend.

A live attempt is durably claimed before submission. Ambiguous submission,
stranded input or failed acknowledgement keeps the inbox pointer and does not
retry the live send. Read it through `st inbox`; sender success means persistence,
not live arrival. A stopped/overloaded tend schedule, down recipient, malformed
queue or incomplete unread coverage prevents a wall-clock delivery guarantee;
those cases remain visible/UNKNOWN and require the normal inbox read path. The
feature is source-only until reviewed adoption and a separately authorized scoped
trial proves the actual scheduled path and declared-exemption coverage. Rollback:
set the scoped policy OFF, drain/read retained pointers, then revert the source;
do not remove unread messages or revert while routine entries remain pending.

## Large durable inboxes

On the native Seeds reader, `st inbox --count` counts message membership without
loading every message’s metadata. Listing shows at most the newest 100 messages
and prints `showing N of M` when more are unread. `st inbox --read` selects up to
15 oldest messages, then uses the existing fresh receipt checks and independent
closes. Undated messages sort after dated messages in both views; ties use stable
message IDs. Explicit `--read-id` selection still reads only those receipts.

The membership count and selected metadata are separate observations, not an
atomic snapshot; concurrent changes can require retrying a read. Unsupported
owner statuses, duplicate receipts across graphs, legacy format uncertainty and
transport failures remain UNKNOWN. These bounds never authorize bulk draining
an operator’s inbox; reading and acknowledging stay separate actions.

Successful administrator deferral digests emit
`deferral-sweep: ADMIN-DIGEST delivered count=N digest=HASH` in the tend log.
Quiet `deferral log:` reports, owner reminders, duplicate suppression and failed
administrator delivery do not emit this marker. Measure the 24-hour acceptance
window only after verifying the installed source and a scheduled tend pass;
count delivered digest markers, rather than quiet report headings or item counts.
Each delivered digest finding also has a `deferral-route:` JSON record binding
the item, finding state key, finite routing reason, recipient, delivery outcome
and digest hash. Owner/lead deliveries have the same fields with a null digest.
No notes, exception bodies or credentials enter these records. `source_sha256`
identifies the two observed routing source files; `UNKNOWN` retains a source-read
failure without blocking notification. It does not certify the bytes imported
before an on-disk source update. A failed administrator delivery is `pending`,
not `delivered`; a suppressed identical summary is `suppressed`.

Ordinary owner/lead routing also emits one `deferral-recipient:` JSON record per
recipient considered. It distinguishes `recipient-absent`, `live-absence`,
`send-failure`, `send-unconfirmed`, `delivered` and `suppressed`. Records bind the
item and finding state key, assignee, recipient role, observation time and source
hash. A bounded snapshot records the card name, pane, retirement/stopped status,
pane existence and recognized runtime as those checks are reached. Unreached
checks remain absent. Lead lookup records the bounded declared lead, resolved
card role and eligibility or lookup exception class. Probe failures retain only the exception class; send
failures likewise retain the class without its message. Raw process commands,
notes and message bodies are excluded. These observations do not prove later
inbox consumption or reconstruct historical delivery custody. Diagnostic sink
failure does not change routing or reminder suppression.

Rank proposals distinguish `reowner` (a positively observed down owner) from
`needs_owner`. An unassigned item at deterministic P0/P1 that is `open` or
`in_progress` needs an owner, with an `owner-assignment` fact citation. Missing
owner observations and held owners do not become down observations. This flag
never assigns anyone or releases a hold.

For a frozen independent corpus, add `--rank-semantic-only` to
`st work triage --rank-proposals --benchmark cases.jsonl --rank-rules rules.json`.
This mode calls only the automation and personal-need nouls, including P0 cases;
rank-band choices are disabled. Each case needs both independent boolean labels
under `expected.flags`, a dated before snapshot, owner evidence, source and rule
references. Unknown ownership labels may remain unknown because this report
scores only the semantic columns. The entire 30–50 case corpus is validated
before any model call; the shared budget is at most 100 nouls. Dry-run makes no
model calls. Real calls still require the explicit verified quarantine graph,
private request journal and exact readback. Missing observations stay missing,
not false. The separate semantic report schema cannot authorize a live rank arm.

Deterministic bands use proven open blockers, not a stored blocked/deferred
status or a `blocked:*` claim. Positive open blockers, explicit
`blocked:human`/`desk`/`needs-stiwi`, keep a blocked band. Parked-by-design work with proven zero blockers is later;
with positive blockers it stays blocked.
With proven zero blockers, other blocked labels produce a visible stale-gate
flag. An open or deferred P0 behind a proven stale gate is immediate.
P0 overdue work or a proven prerequisite of P0 work is immediate; work
due within seven days (including overdue work) is due; other P0–P2 work is
normal and P3–P4 work is later. Missing blocker evidence yields UNKNOWN, never
a zero count. Native snapshots use bounded candidate-edge and exact endpoint
status projections; missing or shadowed endpoints refuse the run. These bands
and flags do not change lifecycle status, clear a hold, or authorize dispatch.

## Processing ACK and DEFER for repeated inbox content

Receipt acknowledgement (`--read`, `--read-id`) confirms delivery. It does not
mean the recipient has handled the subject, and does not silence a new pointer
with the same body. Use an explicit processing decision for that:

```sh
st inbox --ack-id msg-EXACT --reason 'Tracked on the existing incident'
st inbox --defer-id msg-EXACT --until 2026-11-15T07:00:00Z --reason 'Await natural deploy'
```

These commands require your own recipient identity and an exact receipt from
the selected inbox backend, including receipts already marked read after live
delivery. An unknown or foreign ID refuses. `--dry-run` performs no write.
DEFER requires an explicit timezone and a future deadline within 30 days.

A processing ACK silences future **identical recipient, sender and full-body**
repeats. DEFER silences those repeats and makes the original durable receipt
eligible once at/after the deadline, on the next ordinary inbox/startup/tend
read. It does not launch an agent or promise a timer wake. Receipt acknowledgement
after that presentation retires the reminder; the original evidence stays in
the inbox backend. You can explicitly defer that original receipt again.
Changed findings, severity text, sender or recipient remain eligible immediately.
When a caller has no declared sender but the native store derives one from its
credential, the sender persists first and reads that exact receipt before a live
submission. Matching controls silence the live repeat; changed native senders
pass. An unreadable binding retains the durable pointer without submitting it.
This path can retain another evidence record while still preventing context spam.

Decisions are atomic, read-back-verified local delivery metadata under
`<root>/inbox-dispositions/<backend>/`. They survive process/session restarts
using that root; **they do not propagate to another host/root**. `--count` still
reports stored unread pointers. A bounded list may show fewer eligible messages;
that does not mean the retained pointers disappeared. Ordinary reads expand the raw
window up to 100 rows to fill an eligible batch behind suppressed receipts. If
that bound cannot establish a full batch or exhaustion, the read returns UNKNOWN
without acknowledging anything; exact receipt-ID reads remain available.
At most 64 due original
receipts are fetched per read, with a 1024-decision capacity; exceeded or malformed
state reports UNKNOWN rather than treating unreadable state as an empty inbox.

This changes presentation only: no incident resolution, Alertmanager silence,
work-item deferral, credential change or runtime authority follows. No automatic
processing decision is inferred from live delivery, reading a message, an agent
stop, or an old approval. Unkeyed ephemeral send-keys traffic is outside this
inbox control; durable alert producers must use `st inbox -d` for this contract.

## Explicit file-memory transport

`st agent memory` earns its own slot because commit and projection have data
consequences; they must not be hidden in the read-only anchor. The command
provides bounded explicit transport. An independently enabled per-crew Claude
plan can also use the managed lifecycle described in [crew memory](crew-memory.md).
The default installs neither native selection nor automatic synchronization. Run
`st agent memory alpha capabilities` for the current honest adapter limits.

Inspect a selected native directory without uploading its bodies:

```sh
st agent memory alpha inspect --directory /path/to/selected/memory
```

Inspection uses a one-second worker plus at most 250 ms of cleanup, and emits
only complete bounded metadata or UNKNOWN. Original files remain unchanged.

Remote operations require explicit `--server`, `--deployment` and `--project`
IRIs and the existing named CLI credential selection. `read --owner IRI` is
intentionally cross-crew and returns attributed historical data. Other-owner
commit, delivery and staging refuse. `commit --request request.json --outbox
/path/to/private-outbox` durably stores the exact private JSON intent before
reading its receipt and attempting at most one commit. The existing outbox
directory and request file must be private and user-owned. After an unknown
result, preserve both; `deliver --intent NAME --outbox PATH` on a later ordinary
trigger reconciles the original receipt before any identical commit. There is
no implicit retry, deletion or last-writer-wins merge.

`sync --directory PATH --outbox PATH --harness NAME --account NAME` freezes a
bounded multi-file capture and performs one pending-intent attempt by default.
It requires the same explicit remote scope and own credential selection above.
`--max-new N` permits 0..128 attempts; the explicit command also has a two-second
worker deadline plus at most 250 ms of cleanup, regardless of the attempt count.
A timeout is UNKNOWN and cannot undo an accepted remote commit. Invoke it
explicitly again to resume the same pending batch before
recapture. Its journal accepts completion only after a fresh authenticated own
projection matches the final receipt. A different remote head refuses automatic
adoption. Source files and native selection remain unchanged. This command
does not install an automatic lifecycle hook.

`stage --parent PATH` verifies the own-owner export and creates a new exclusive
generation. It does not select that generation, replace native files or alter
harness settings. Existing startup memory bridging remains. Claude native
selection requires the separate default-OFF managed plan and installed handoff
acceptance, Codex generated-memory
writeback is unsupported, and an OpenCode native-memory convention is unproven.
A successful transport command is not native round-trip acceptance.

Within the same explicit scope, `query --owner IRI --text literal` searches
that selected owner's bounded exported records. It is a literal search, not a
global or semantic index. Hits include owner, revision, source harness/account,
commit time and an explicitly truncated excerpt. Retrieved text is historical
source data, not an instruction or current authority. `export --owner IRI`
returns the complete bounded envelope for inspection; it does not supply own
projection identity and cannot select native files. Missing graph/partial or
unreadable coverage refuses rather than returning a misleading empty match.

## Transcript derivatives and credential boundaries

The history Stop hook launches a detached, single-agent archive worker and returns
without waiting for capture or scrub. Both inherited output pipes are disconnected
from the harness. One nonblocking lock per agent prevents overlapping workers;
an overlapping stop is coalesced into the active worker, and subsequent stops can
capture later transcript growth. Completion and failure remain in `hook.log`;
worker diagnostics go to the private raw archive's `worker.log`. A successful
launch is not archival acceptance. The worker retains the scrub residual check
and never publishes raw history. `--worker` runs the same work in the foreground
for diagnostics and tests; no additional timer is installed.

Capture and scrub preserve citation symlinks when cold archives are relocated.
Unchanged captures inspect the target size; growing captures and regenerated
derivatives publish atomically beside the private archive target. Relocated
files must retain the agent directory and filename, be owner-only, and have a
private parent directory owned by the same user. A filename may also carry
`.recaptured-<sha256>` with a 12-to-64-character lowercase hash prefix matching
its original bytes. Before updating that layout, publication preserves the
hash-verified origin in a private `.history-origin-*` file and each predecessor
in `.history-preserved-<full-sha256>`. Later scrubs verify the retained origin,
keep the citation target unchanged, and retain all versions. These version
files are archive evidence, not temporary files to remove during a scrub.
Publication holds a private per-target `.history-publish-*.lock` through
preservation, staging and replacement. A competing publisher refuses without
overwriting the current version; a later normal capture can try again. These
lock files remain in place so concurrent publishers cannot split the lock inode.
An altered origin, wrong hash, unsafe ownership/mode, dangling or mismatched link
is refused rather than replaced. Derivative links into the raw archive are
refused. Editing the scrub policy triggers a normal re-scrub of old derivatives.

The raw transcript archive stays local and unindexed. `st-history-scrub.sh`
creates a separate derivative: it omits supported harness tool-result objects
wholesale, including nested Claude results and their `toolUseResult` mirrors,
Codex call outputs and tool-role
messages. Unparseable records are omitted rather than copied without a known
schema. The raw records remain available for investigation.

Retained dialogue, reasoning and tool invocations receive credential-pattern
redaction. Private-key PEM envelopes are redacted with their full body; an
unfinished envelope removes the remaining text in that string. The directory
name `history-scrubbed` does **not** mean arbitrary
credentials are absent: an unrecognized value pasted into dialogue can remain.
A successful scrub proves only the named patterns and supported result types
are absent. Off-host publication needs its own credential checks.

Each derivative records the exact scrub policy that produced it. A policy
change rebuilds older files despite their modification time; skipped files
still undergo the residual check. Writes are private and atomic. The corpus
projector independently excludes tool results as a security boundary, and its
version invalidates cached projections when that boundary changes.

Run `python3 -m pytest -q tests/test_history_archiver.py tests/test_history_corpus.py`
to exercise both directions: unshaped canaries are removed from results while
ordinary dialogue controls survive, and a contaminated current derivative
makes the scrub fail.
