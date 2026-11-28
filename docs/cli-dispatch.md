# Dispatch and intake

`st go`, `st sling` and `st task`: how work reaches an agent, how intake is ranked and what stops a dispatch. This page is part of [the CLI reference](cli.md).

## `st sling` — design handoff

Design → bead (epic and children) → `st sling <bead>`. The executive administrator
owns scheduling and worker dispatch. This command does not claim or dispatch the design.

```sh
st sling design-42 --note-file handoff.md --dry-run
st sling design-42 --note-file handoff.md
```

Mark exactly one administrator with the additive `executive` role in the role
registry: `role = "administrator"`, `roles = ["administrator", "executive"]`.
Keep its host placement current. This marker does not create a new tree position.
An absent, ambiguous, retired, or non-administrator executive refuses delivery.
For files registries with peers, the configured graph supplies fleet identity;
without a graph, a complete peer census is required. An unavailable source refuses
rather than choosing the first administrator.

The bead must have a nonblank description or design body. The full note and direct
parent-child references are recorded in a structured handoff comment. A bounded
bead pointer goes to the durable inbox (br by default; explicit files is available
for standalone deployments). Receipt read-back is required for success. A live
pane nudge is best effort; the unread receipt remains for the executive's next stop.
Long notes belong in `--note-file` or stdin (`--note-file -`), never shell interpolation.

Cross-host handoffs use the same configured peer relay as `st go`; the destination
rechecks executive and host placement and reads its configured shared board.
An explicit local `--repo` cannot be reinterpreted on another host. Both deployments
must have this command installed. `--dry-run` reads the design and previews target,
pointer, children and note without writing a comment, receipt or event.

Each handoff has an atomic event under `<root>/sling/*.json` containing sender,
executive, bead, children, timestamp and verified receipt. The same content retries
with the same marker, including when its inbox receipt has already been read.
After an indeterminate write, inspect that marker before retrying; changed content
is a new handoff. The structured comment provides the same provenance on the bead.

## `st go` — dispatch

Explicitly dispatching deferred work clears its old deadline after delivery is
confirmed, together with the verified active assignment. A dry run, refusal, or
unverified delivery leaves the deferral intact. Dependency and governor gates
still apply; activation does not remove the item's notes or review conditions.

The normal audited dispatch retains a pending attempt before sending. A bare
item ID left in scrollback cannot confirm a new attempt: confirmation uses the
unique serve/worker witness or the adapter's evidence for the exact body.
An unverified send leaves assignment unchanged and retains pending evidence.
A delivery or tracker error does not authorize a manual claim or another send;
reconcile the retained attempt with actual delivery and tracker state first.

This is the command the repo exists for. `gt sling` takes >120 seconds; `--dry-run` alone takes 51s
and **writes nothing**, because the cost is 63 sequential Dolt connections during *resolution, before
any write*. Underneath, dispatch is `tmux send-keys`.

```
$ st go st-9h2 ellie

  st-9h2 -> ellie          in progress
  sent to pane %5             0.4s
```

```
$ st go st-9h2 ellie --dry-run

  would: tracker.update(st-9h2, status=in_progress, assignee=ellie)
  would: send-keys -> pane %5
  would NOT: create a convoy, spawn a session, wait for ack

  0 writes. 1 tracker call, 1 send-keys.
```

**`--dry-run` is non-negotiable and it is first, not last.** A real sling was fired as a diagnostic
during this design and hooked an agent with work nobody meant to assign. *Make the question askable
without the consequence.*

Use `--dry-run --reassign` to preview deliberately taking an item from its current
assignee. The override applies to preliminary triage as well as the dispatch plan;
the governor and pane checks still apply. The preview neither updates the tracker
nor sends input to the pane.

### Every dispatch names its STORE

A dispatch used to be an id and a title. This host has **125 bd stores** (measured 2026-08-01), of
which **11 are embedded** — reachable by no amount of thoroughness against the Dolt server. So an id
alone is not underspecified, it is *unanswerable*, and worse: **a cross-store dispatch and a phantom
id are the same observation.** Measured cost (malcolm, 2026-08-01): dispatched an item, could not
find it in the default store, swept every database on the server with validated positive controls,
got zero rows, and concluded it existed in **no** store. It existed — in an embedded one. The wrong
conclusion shipped as `confidence:extracted` and a lead reinforced it before both were retracted.

So the store rides the payload, always, as the command you would type:

```
$ st go st-9h2 ellie --dry-run

  would: tracker.update(st-9h2, status=in_progress, assignee=ellie)
  would: send-keys -> pane %5
  would: name store -> [st store: cd /opt/rigs/aegis && br]
```

When the item is genuinely **not** in the store the recipient's own workspace resolves to, the tag
stops describing and starts warning — naming both sides, because "this is elsewhere" without saying
elsewhere-*than-what* is not re-checkable:

```
  would: name store -> [st store: cd /opt/work/sidecar && br — DIFFERENT STORE
         from your workspace's (embedded:/opt/work/sidecar/na vs
         db.invalid:3306/beads_aegis); selecting this directory is REQUIRED, the id will NOT resolve without it]
```

Three properties worth knowing:

* **The tag is unconditional; the warning is not.** Naming the store only "when it differs from the
  default" requires being right about the recipient's default — but `br` resolves from the *ambient
  cwd*, so that is a function of where the agent is standing when it types, not something this
  process can compute. A conditional built on a guess goes silent in exactly the case that costs a
  day. Naming it always has no failure mode.
* **Stores are compared by identity, not by path.** The same store has many paths, and not rarely:
  16 of those 125 paths resolve to the one database `db.invalid:3306/beads_aegis`, because
  `~/gt/beads_aegis/.beads` holds no metadata — only a `redirect`. Path equality would have shouted
  "different store" at 15 of 16 *correct* dispatches, until the warning meant nothing.
* **A store we could not read is never reported as different.** "I could not read its metadata" is
  not evidence of difference; rendering could-not-tell as a finding is the same error the incident
  was.

The other half is on the read side: when an id fails to resolve, the error now names the store it
searched **and counts the ones it did not** — absence with a boundary is re-checkable, bare absence
is what invited the generalisation.

### `--note` / `--note-file` — a caveat that rides WITH the work

```
$ st go aegis-9h2 ellie --note "a design doc is landing; pull YOUR OWN workspace, do NOT blind-pull"

  aegis-9h2 -> ellie          in progress
  sent to pane %5
  note: a design doc is landing; pull YOUR OWN workspace, do NOT blind-pull
```

Dispatch used to be item-and-agent and nothing else, so a qualifier had nowhere to go. Both
workarounds were wrong in a specific way:

* **`st inbox` after the go** — `send-keys` into a pane that has *just started work*. That is exactly
  the mid-flight garble `go`'s triage refuses; sending it by hand routes **around** the safety.
* **a bead comment** — durable, but out-of-band and permanent. The note was about *this dispatch at
  this moment*; it lands on the **item**, for every future reader. Measured (sattler, 2026-07-19):
  four beads left carrying a pull warning that was stale inside a week.

`--note` is composed into the **same payload**, so it passes the same triage gate and the same
verify. The work and its caveat are delivered together or refused together — and that atomicity is
the point: **a caveat that arrives separately from the work it qualifies can arrive after the worker
has already acted.**

Two properties worth knowing:

* **The note is flattened to one line.** The transport is `send-keys -l <text>` plus a separate
  Enter, so a literal newline in the payload is a *submit*. An unflattened three-line note would
  dispatch line one and type the rest into a pane already working. `--dry-run` previews the note
  **as it will be sent**, and a successful dispatch echoes it back.
* **`--note-file <path>` (or `-` for stdin) for anything long or quoted.** Prose in a shell string
  gets `` `...` `` and `$(...)` expanded before `st` ever sees it — the note either runs or is
  silently deleted while the command reports success. A file is inert.

An unreadable `--note-file` is a **refusal** (exit 1, nothing sent, nothing written), never a
note-less dispatch: sending the work without its caveat is the failure this flag exists to close.

### The performance budget is a test, not an aspiration

`st go` must be **under one second**, and the test asserts the *mechanism*, not the stopwatch:

```
tracker calls:  <= 3   (resolve, write, READ THE WRITE BACK)
connections:    <= 1 per backend
sends:          1
waits for ack:  0
```

Count the connections. A stopwatch on a shared host is exactly the kind of number that flatters — the
`gt sling` regression would have passed a "feels fine" check on a quiet night. **The observable is the
count.**

**The ceiling moved from 2 to 3, once, and only to buy a read-back.** `st go` was printing
`-> in progress` while the tracker row stayed `open` and unassigned — intermittently, on the same
binary and store that had worked minutes earlier. The send landed; only the write vanished, at exit
0. So the item never entered the worker's haul, `st crew` showed them idle right after a successful
dispatch, and the bead re-entered `bd ready` to be handed to somebody else — duplicate work arriving
underneath the assignee guard built to prevent it.

The distinction that keeps the budget meaningful: it was written against **resolution churn** — 63
sequential connections to answer one question before any write. A single read that confirms the write
landed is not that. **A budget is a guard against work that buys nothing, not a reason to report a
write nobody confirmed.** Anything wanting a fourth call has to make its own case.

A dispatch that needed more than one write+read-back round still succeeds, and says so on stderr —
the fault is intermittent, and one that is silently absorbed is one nobody can ever root-cause.

## Dispatch receipts

When a pending dispatch has a different scope, the refusal names the retained
receipt ID, original worker, state and revision. Its printed `--reconcile`
command uses that original worker, even when the refused request named someone
else. Reconciliation is read-only. For a prepared or interrupted-assignment
receipt whose native item is open, unassigned and undeferred, the message also
prints the explicit `--supersede` command. Neither command is run automatically;
supersession still checks its own current native release proof.

A dispatch that remains `prepared` can be explicitly retired with
`st go ITEM WORKER --supersede --receipt RECEIPT_ID` after a fresh native read
proves the item is open, unassigned and undeferred. This path requires that no
submission or assignment witness was recorded and no native claim was started.
It preserves the old body and evidence, sends nothing and claims nothing.
It does **not** assert that the text was never delivered: even a late delivery
of that old ID remains unauthorized. A later ordinary dispatch creates a new
receipt and must pass the normal pane/composer gates. `--dry-run` only previews
the retirement. A receipt at the uncertain assignment boundary still requires
a **newer** native open/unassigned release; this recovery does not relax it.
When the native item was read exactly but is not eligible (for example deferred
or assigned), supersession is **refused** (exit 1) and names the observed
revision, status, assignee and defer plus the release it needs. The same holds
for an interrupted assignment whose native item is read but not newer, open,
unassigned and undeferred. A native read that is refused, unreadable or names
another item reports `UNKNOWN` (exit 2), with the store's reason for a refused read.

Seeds and file-backed `st go` persist a pending receipt before sending. The
receipt binds the task revision, worker card, pane/session/process generation, note, graph context,
store and exact body. The payload names that receipt and asks the recipient to
check its acknowledgement before executing. Planning or typing alone grants
no assignment: exact-body submission must be observed, followed by one
revision-guarded tracker transition carrying the same receipt and body digest.

Read its current state without sending, claiming, changing the ledger, or
forcing input:

```sh
st go project-item ada --reconcile --receipt RECEIPT_ID
```

`execution_authorized` requires current scope and native assignment proof.
Missing submission, assignment, or local persistence is named separately; an
unreadable native proof remains UNKNOWN. A native commit whose local receipt
write was interrupted can still be proven by read-back. Repeating the original
`go` then repairs local persistence without a second send or claim. A pending
unverified send refuses replay until its retained transport evidence is
reconciled. An exact delivered record in existing transport custody can repair
the local observation on normal replay, without another send; queued or merely
acknowledged custody does not qualify. Never resend or claim manually. Changed revisions, workers, notes,
cards or sessions cannot reuse the receipt. Older tracker adapters retain the
legacy path and do not emit bound execution receipts.

`st go ITEM WORKER` for an item already `in_progress` for that same worker,
with no receipt covering its current scope and none pending, refuses (exit 1)
before minting a receipt; `--dry-run` refuses identically. Nothing is written
or sent, and the worker proceeds on the native assignment it already holds.
A fresh receipt for work the worker already holds would tell that worker to wait
for authorization. When its submission to the busy holder could not be proven,
it stayed `prepared` and wedged the worker. To send such an item again, release
it to open first. An assigned receipt whose scope still matches replays as
before, and a pending receipt keeps its `--reconcile`/`--complete` path.

If observation was interrupted, the dispatcher can explicitly complete the
original receipt on the worker's declared host:

```sh
st go project-item ada --complete --receipt RECEIPT_ID
```

This sends no text or keys. Current ownership, blockers, capacity, governor and
operator holds still apply. It preserves the original request and revision;
it never accepts replacement notes or a caller-provided submission assertion.
Claude proof can come from its exact native user record, or a consumed busy
command whose exact body, session, command ID and delivery ID match both the
native queued-command attachment and absorption acknowledgment. Queue custody,
quoted output and discarded commands do not qualify. The current hook, stats,
workspace transcript, pane session and runtime must agree. Missing or changed
evidence leaves the receipt fenced. An uncertain native claim is read back;
completion never repeats it. `--dry-run` and `--reconcile` remain read-only.

File-backed tracker updates now serialize per item and increment a revision
with the assignment and transition comment in one atomic file replacement.
Existing unversioned files occupy revision one. Reads and dry runs do not
migrate or rewrite them.

## Assignment capacity

### Ranked intake and dispatch admission

`SHANTY_QUEUE_POLICY=enforce` enables the Seeds queue contract. The default is
`off` for compatibility with unlaned deployments; any other value refuses.
Activation and migration of existing plates are separate operator decisions.
`st task` checks the bounded Now/Next cohort, creates the item, then CAS-writes
Next and an exact decimal append rank. It prints the observed position, an
UNKNOWN likely start when no duration evidence exists, and the current Now
items a request for immediate work would need to disposition. It never guesses
a date or silently demotes an existing item. A full or unranked Next queue
refuses before creation. Native lane caps remain authoritative under races.

Seeds currently lacks `create --lane`: a failed or uncertain follow-on write
prints the created ID and returns UNKNOWN. Reconcile that ID; repeating create
would duplicate the request. Successful intake requires verified lane/rank and
a complete post-write queue observation. Dry runs perform no writes.

With enforcement on, fresh `st go` refuses anything outside Now or behind the
head of the target's ranked plate. Existing active custody retains precedence;
priority is severity, not ordering within Now/Next. Missing lane/rank or partial
reads refuse. Existing governor, dependency and ownership checks remain active.
Pending dispatch receipts still reconcile without re-sending: this does not
retroactively revoke custody already delivered by an older binary.

Assignment follows the same order as dispatch. With enforcement on, `st task -a`,
`st work item update --assignee` and `st go` refuse to give an item to a new owner
when it has no Now/Next rank, or when an unassigned, open, workable item ranks
above it on the board (Now before Next, then rank). The refusal names that item.
`--queue-override REASON` assigns anyway: the reason, actor and refusal are
written on the item's transition and counted with refusals in `st agent stats --queue-order`
(`out_of_order_overrides`). An unreadable board refuses and cannot
be overridden. `st task -a` that is refused still files the request into Next,
unassigned. Off mode never reads the queue and rejects `--queue-override`.

`st work item update ID --lane now --rank 1 --quote 'Do this now' \
--requester operator --urgent --if-revision REV` records the exact request and the
current Now cohort in the same native CAS as promotion. Caps refuse and name
displacement candidates; the command never automatically evicts another item.
The declared requester must match `SHANTY_QUEUE_REQUESTER` from the deployment
policy, and the quote must contain the explicit word "now". An absent requester
policy refuses promotion. `--urgent` affirms the caller is recording that request. This lexical
check does not authenticate authorship or interpret the request's meaning.
These fields declare provenance, not authentication or a governor override.

Actual queue refusals are appended to the existing feed audit before the
dispatch returns. `st agent stats --queue-order` reports retained observations;
missing, malformed or over-budget history is UNKNOWN. It is not an all-history
fleet counter or proof the policy is activated. Rikuy producer/query/display
activation is separate from this local reader.

### Explicit intake deadlines

`st task --due 2026-12-01 "review the draft"` creates the item with a due date
in the same tracker transaction. Date-only values mean midnight UTC; an ISO
instant must include its timezone and is normalized to UTC. Relative dates and
timezone-free instants refuse rather than depend on the host's clock settings.
`--dry-run` validates and prints the deadline without creating an item.

Deployments may set `SHANTY_TASK_DUE_REQUIRED=1` to refuse missing deadlines
before tracker reads, duplicate advice, capacity checks or writes. The default
remains optional for other deployments; the command never invents a deadline
from priority or owner. This affects `st task`, not direct SDK creation or
internal message records. The existing agent duplicate advisory still runs on
admitted creates; a skipped or capped advisory is not proof of no duplicate.

### Duplicate intake

`st task TITLE --description TEXT` forwards the description to the Seeds intake
resolver. Seeds refuses near-duplicates and names existing items to comment on.
If the work is distinct, use `--new-despite ID --because "reason"` (repeat
`--new-despite` for every candidate). The Seeds create transaction records the
reason, candidates and related edges. These flags require the Seeds backend;
resolver failure does not turn into an advisory or an automatic retry.

### Graph-ranked pickup after an anchor ends

Deployments may enable `SHANTY_BACKLOG_PICKUP=1` after registering the reviewed
`queries/seeds-work-rank-v2.ttl` stored query as `seeds_work_rank_v2` and verifying
that the installed consumer selects that exact version. The original v1 query
belongs to the earlier v1 consumer; v2 never falls back to it. Registration and
enablement remain separate admitted deployment steps, and pickup defaults off.
At a worker's completed-anchor stop, the hook compares its assigned queue with
strictly higher-priority READY unowned work. The query orders up to 64 exact
candidates by declared priority, due/overdue date, explicit directive, capped
observed deferral lower bound and age. Missing historical deferral observations
remain UNKNOWN, not zero. Current revisions, owners, dates and statuses must
match the query witnesses before selection.

The selected unowned item is claimed with a revision guard, the ordinary plate
capacity lock/check, fresh dependency readiness and verified owner read-back.
The old assigned queue remains intact. A conflict retains admitted old work;
an indeterminate claim stops pickup for reconciliation. No active anchor is
preempted, no other live owner's item is taken, and background or unreadable
process custody prevents the switch. Governor, feed holds, host scope,
session ceilings and context handoff still apply. Leads and keepers retain
their existing selection behavior in this first slice.
Deployment-operation labels and all nonempty native agent contexts are refused
by this claim lane; their phase-CAS controller remains the only owner.

This is an opt-in pickup slice, not the complete backlog policy. It does not
promote dependency priorities, cull deferred work, manufacture due dates or
switch an unfinished active anchor. Those decisions remain visible work.
The default path and non-Seeds deployments retain their existing behavior.

Ordinary assignments are capped at ten active work items per crew member. Open, hooked,
in-progress and blocked tasks count; closed, tombstoned and deferred work,
future-dated deferrals, messages and permanent records do not. `st crew`
shows `plate: N/10`, and its JSON rows expose `plate_size` and `plate_cap`.
An unreadable count is UNKNOWN (`null` in JSON), never zero. A full refusal lists
the exact `counted_ids`, including blocked work that is absent from the visible
ready plate. Closing inbox messages or repooling excluded alarm records does
not free a work slot. Admission reads fresh owner membership; it never borrows
the frozen observation used to render a crew report.

ASK-class records waiting on Stiwi also use no work slot: the shared ASK labels,
an `ASK Stiwi` title prefix, or a structured `blocked:human` blocker identify
them. They stay owned and visible, and the no-deferral rule still applies.
Ordinary external dependencies and unknown classifications still count.
Label names come from comma-separated strings, lists of strings, or name records;
malformed top-level maps and scalar values do not grant a capacity exemption.
Turning an ASK record into ordinary active work requires fresh capacity.

`st go` refuses a new ordinary assignment at capacity before sending or updating the
item. `st task --assignee` at capacity still creates the requested work item,
prints its ID, leaves it unassigned in the pool and returns refusal. An
unknown count refuses without creating anything. Dry runs make no writes.
The exact-ID work update path applies the same gate to assignment and
reactivation. Haul/feed may resume an already-owned active item at ten because
that does not add a slot; existing overfull plates are not silently repooled.

The ten-item limit applies to every priority, including P0 and inherited P0
blockers. Urgency changes queue order; it does not grant another work slot.
Rebalance existing work before assigning another item. Historical overflow
journals are retained unchanged; new assignments do not append to them.

Cooperating assignment commands on one host serialize admission and mutation.
The configured owner reader must cover all selected stores; partial reads
refuse. This is not an atomic cross-host backend limit: direct tracker writes
and independent writers on another host require a backend admission contract
or a single assignment writer. No force or hold override grants a cap exception.

## Hold automatic feeds while staying live

Use a per-agent feed hold when the pane should remain reachable but receive no
automatic haul continuation, advance or idle-worker feed:

```sh
st work hold-feed ada --until 2027-01-01T18:00:00Z --reason-file reason.txt
st work hold-feed ada --status
st work hold-feed ada --clear
```

An expiry may be a UTC date/time or `closed:project-item`. A date expires on the
next feed read; a closed-item condition uses the selected deployment's exact-ID
reader. An unreadable condition or hold record keeps automatic feeding held.
Expired records remain as provenance and do not block feeding. A replacement
hold takes effect immediately; an older expiry cannot remove it.

The hold is stored on the agent's declared host. An off-host or unresolved-host
request refuses before writing; select the target deployment through the existing
CLI execution lane. The hold is durable and appears in the human `st crew` and `st anchor` views.
It does not stop, retire, cycle or relaunch the agent, cancel a queued cycle, or
block explicit `st go` and inbox delivery. It does not grant dispatch permission:
all existing busy-pane, budget, stop and ownership gates still apply.
`st agent stop --after-turn` retains its separate stop intent.

This command earns its own slot because creating feed intent is a write with
an expiry and reason; hiding it on a crew read or using the stop command would
change what an operator's existing command means. `--dry-run` validates the
request and writes nothing.

## Haul delivery after queue changes

The Stop hook reads the current assigned queue at each boundary; work assigned
mid-turn can be selected immediately. Tend's idle fallback also rereads the queue
before deduplication. It remembers the next item it delivered, so a new assignment
or a completed turn between two idle observations re-arms delivery. Appending more
work behind the same next item does not resend it. Input preflight, session ceilings
and delivery receipts still apply; a tracker claim alone is not proof a turn began.

For a native Seeds board, the Stop hook reads only the current owner's active
anchors across the shared and ephemeral graphs. It retains priority/creation/id
order and future-dated active work. An incomplete or unproven native read allows
the stop without claiming new work; it does not retry through a global issue
listing. Proven legacy boards retain the existing CLI path. The global ready-work
priority advisory is unchanged.

Both haul triggers honour a current deliberate-stop stamp and a gaming hold before
claiming or resuming work. A held pass spends neither delivery dedup nor the resume
backoff. Release the hold through the existing lifecycle or gaming controls.

Before selecting new work, both haul triggers apply the target card's governor
verdict, including its harness-specific priority floor and explicit exemptions.
Refused items remain assigned and ready; the log names each item as `parked by
governor`. An admitted item later in the queue can still be served. A fully held
queue spends no claim, session item, delivery receipt, or context-cycle prompt.
Existing active anchors remain continuations rather than new admissions.

## Tracker commands in haul instructions

The haul feed, active-anchor resume, and `st ops help haul` render command examples
from the tracker selected for that deployment or explicit CLI invocation. Seeds
examples include the server and named graph reported by `sd where --json`; local
store examples require the exact existing file. A single-store br deployment
retains its configured executable and repository directory. No board read or write
is needed to exercise the formatting fixtures.

Unknown backend or unproven routing produces a routing diagnostic instead of
mutation recipes. A multi-store br deployment also omits examples because a generic
help page cannot identify the item's store. Resolve routing before changing work.
The renderer does not change claim, defer, close, or re-pool behavior.

Graph-context suggestions use the same selected tracker as dispatch and cycle.
The caller passes the authoritative item ID, title and description to Camayoc's
version 1 work-item JSON interface through stdin. A failed or incomplete item
read reports an unknown hint; it does not resolve the ID through another board.
The suggestion remains inferred and does not replace asserted context. The
updated linker interface must be installed before the updated caller.

After a deployment switches its board to Seeds, use its reviewed default backend
or explicitly select `--backend seeds`. Explicit `--backend beads` still selects
the br transport; it is not a Seeds alias. A missing ID on that explicitly
selected board is not permission to retry against another board.

## Untaken higher-priority work

`st go` prints a governor advisory when it dispatches lower-priority work while
higher-priority ready beads remain unassigned or belong to an agent observed down.
The message gives the total and up to three IDs. Dispatch remains permitted;
`--reason <text>` is an alias for `--note` and records why the lower-priority
choice is appropriate. Prefer `--note-file` for longer explanations.

Both haul advance triggers include the same advisory in the next-work message;
tend also logs it. The crew and tend reports name waiters when a live agent has
lower-priority active work. `crew --json` includes `priority_advisories`.

Observation-only consumers may use `crew --local --json --no-priority-advice`
to omit the optional board-wide priority scan. The field explicitly says the
advisory was not measured; pane, assignment and unknown-state checks still run.
The flag is refused with other modes. Default crew and dispatch advice is unchanged.
Deferred, dependency-blocked, decision, record, and anchor beads are excluded.
An assigned owner whose liveness cannot be read does not count as down. An
unreadable queue produces an unavailable advisory, never a zero-waiting claim.

There is currently no bead-to-role domain matcher in the dispatch/haul model;
this advisory does not invent one from labels. Existing governor admission
checks remain authoritative. A bare tracker assignment bypasses the immediate
`st go` message; crew/tend detects it once the item is active on a live agent.
The advisory never reassigns work or changes priorities.

## Agent create duplicate advisory

When `SHANTY_AGENT` is set, `st task` checks up to three indexed open candidates
from Bobbin's `search_beads` HTTP endpoint (`GET /beads`) and verifies each against
the selected tracker store before asking Camayoc's `jev_noul` whether it describes the
same concrete work and acceptance outcome. A probability of at least 0.90 warns;
creation still proceeds. Verdicts remain inferred and are never published to the
board or knowledge graph. No warning is evidence of exhaustive duplicate absence:
retrieval is bounded, indexed open status can lag, and in-progress items are not
retrieved by this initial open-only filter.

Configure `BOBBIN_SERVER` and `SHANTY_CREATE_JEV_COMMAND` (the same quoted argv
used by `st work triage --jev-command`). Missing configuration, failed reads,
invalid responses and timeouts print `advisory skipped: <reason>`. There is no
lexical fallback. A separate process group is killed after 1.6 seconds, leaving
headroom for startup and rendering within the two-second advisory budget.
Dry runs and creates outside an agent environment do not invoke it.

A deployment's PreToolUse Bash chain can call the **same implementation** using
the installed st Python interpreter:

```sh
python -m shantytown.create_advisory --envelope
```

Pass the original hook JSON on stdin. `SHANTY_ADVISORY_PRIOR`, if present, contains
the existing hook JSON envelope; its context and permission fields are preserved.
The adapter requires both `SHANTY_AGENT` and a hook `session_id`, recognizes literal
`br create`/`br-aegis create` titles and descriptions, and never executes shell
text. Compound creates, substitutions and unsupported options produce a skip.
Quoted mentions and heredoc bodies are not creates. Producer scripts are not
instrumented, and the tracker backend itself is unchanged.

For Seeds-backed `st task` creates, candidate verification retains the selected
Quipu, graph and prefix and proves that store before reading the exact candidate.
An unavailable or unproven store skips the advisory; it never falls back to a
legacy local board. Search, candidate-store and judgment failures use distinct,
bounded reasons without recording private exception text.

Every considered advisory appends `fired`, `skipped` or `no-match` and elapsed
milliseconds to `~/.local/state/shantytown/create-advisory.jsonl` (override with
`SHANTY_CREATE_ADVISORY_LOG`). It includes event IDs, candidate IDs, probabilities,
model/usage and request/title hashes; it does not persist title/description text.
Telemetry failure is visible. After a week, independently label fired events in
JSONL, one `{"event_id":"...","duplicate":true}` per reviewed warning. True means
at least one warned candidate represents the same work. Review missing labels and
skips separately; do not infer correctness from whether a user created the bead.

```sh
python -m shantytown.create_advisory --report /path/events.jsonl --labels /path/labels.jsonl
```

The report counts unlabelled warnings and returns null precision when nothing has
been judged. This is distinct from the frozen synthetic 30-pair smoke evaluation
in `tests/fixtures/create_advisory_pairs.jsonl`; synthetic precision is not measured
precision on real creates. Neither report enables blocking.

A separate report-only command measures the retained seven-day population:

```sh
python -m shantytown.create_advisory --coverage /path/events.jsonl
```

It reports skipped and evaluated events separately, with bounded skip-reason
codes. Missing, malformed, duplicate or oversized logs return an unknown report
and exit 2. An empty population has null skip ratio. This command does not create
items, query the tracker or invoke a model. Coverage is not precision, and retained
logs alone do not prove that every create was instrumented.

## Board triage (Jev)

For read-only governed P0/P1 priority/rank proposals, use
`st work triage --rank-proposals --rank-rules reviewed-rules.json --dry-run`.
See [governed rank proposals](board-rank.md) for policy bindings, UNKNOWN
liveness, the frozen benchmark and quarantine-only answer artifacts.

`st work triage [item ...] --jev-command 'python3 /path/to/camayoc/scripts/jev_mcp.py'`
previews routing, duplicate and escalation severity suggestions. This earns a
separate work command because it produces advice across the board, unlike
`go` (dispatch) or `dream` (reflection). It uses the deployment's br board and
Quipu crew roles/domains; missing domains are listed, never invented.

The default selects at most five open unassigned non-inbox items. `--limit` bounds
that set; each item makes one choice, one severity score and up to five pairwise
noul calls against lexical duplicate candidates. Lexical similarity only selects
candidates. It never becomes a Jev verdict. The none option remains enabled.
`--dry-run` reads inputs without calling Jev. No API key enters st; the installed
Camayoc server resolves its own credential and records per-agent usage.

`--publish` appends comments tagged `jev`, `sourceKind=inferred`, `plane=quarantine`
with request/model/confidence/usage and verifies the comment read-back. These are
human-review suggestions; no assignment, priority, duplicate link, page or graph
promotion occurs. A changed assignment or an invalid model/transport response
refuses publication. A failure after earlier items were published is partial
progress: inspect those comments before retrying an indeterminate write.

`--benchmark labelled.jsonl` evaluates owner choice on at least 30 historical
issue objects containing `id`, `title`, `description`, and `assignee`. Labels and
priorities are excluded from model state. The JSON report includes agreement,
abstention, confidence split and every request/result. Recorded assignee is the
comparison label, not proof of a uniquely correct owner. Duplicate/severity arms
remain uncalibrated until separately labelled; all output stays advisory.

Initial routing measurement (2026-09-23): 30 distinct closed tasks spanning 13
recorded assignees, sampled in rounds from each owner's latest completed tasks.
An exact domain-predicate query supplied one domain for 14 graph crew choices;
13 were missing. The general registry does not project domains, so triage reads
that predicate separately and refuses partial reads. Jev matched 5/30
labels (16.7%), abstained on 23/30 (76.7%), and made two other choices. This is a
diagnostic baseline, not evidence of routing quality: populate governed ownership
domains and rerun before trusting this arm. No confidence cutoff was inferred
from this small set. Raw requests and results belong with the deployment's private
benchmark artifacts, not in a public repository.

## Task read ordering

Run `st agent stats --begin-task test-123` as a **standalone tool command** before
starting a task, including after changing tasks in the same session. Then call
Quipu search/query/ask through the Homelab MCP tools with `task="test-123"`.
Dispatch and haul prompts include this declaration step. The CLI prints a request
marker; the post-tool hook records it with the harness session ID. Invoking the
CLI outside a hooked tool call does not create a binding. Repeating the current
declaration preserves earlier actions.

`st agent stats --task-order [agent] --since 24` prints JSON with one row per observed
session-local declaration and a count of unbound events. PASS means a successful,
task-matched MCP read completed before the first definite material tool started
in that scope. FAIL means the definite action started before the first recorded
read completed. Missing starts, unsuccessful or absent reads, ambiguous earlier
operations, and scopes with no definite action remain UNKNOWN. Shell commands
are ambiguous; edit/write tools are definite. A successful hook result proves
completion, not the usefulness of the answer.

The report also includes `weak_observation`, labelled
`read-before-first-possible-op (weak)`. Its four buckets are always reported:
`read_before`, `reverse_or_concurrent`, `incomplete`, and `no_matched_read`.
They compare completed reads with recorded definite **or ambiguous** operations.
This observation never changes a verdict, feeds a gate, or supplies an adoption
denominator. A read followed by a shell command can satisfy this weaker ordering
while its strict verdict remains UNKNOWN.

`strict_population` independently counts existing PASS/FAIL/UNKNOWN verdicts for
contexts containing possibly-material operations, including CLI-only work. Its
headline fraction keeps UNKNOWN in the denominator; the separately labelled
secondary fraction is PASS/(PASS+FAIL). Empty denominators produce `null`.
Read-only/no-operation contexts are excluded and explicitly counted with their
context IDs. Incomplete capture is retained as UNKNOWN even when no operation
start survived: missing evidence does not prove read-only work. All four weak
buckets exclude the separately counted read-only/no-operation contexts.

This is **declared-scope evidence, not whole-dispatch coverage**. Undeclared tasks
remain outside this report; reconcile against the dispatch ledger and haul records
before calculating adoption. A declaration made late cannot certify earlier work.
Hooks cannot establish activity they never saw. Concurrent sessions do not borrow
one another's tasks, and a read carrying a mismatched task remains unbound.

Ordering metadata uses separate SQLite tables and stores no command bodies,
queries, responses, or credentials. Existing usage counts retain their successful
post-tool denominator. Both harness adapters provision pre-tool and failure
capture alongside existing post-tool/stop capture on **next launch**. Already
running sessions may lack starts and must report UNKNOWN; installing code does
not prove those sessions adopted new hook settings. No restart is required by
this command.

The stats capture hook fails open on runtime errors and malformed arguments
(including a missing `--root`): it prints diagnostics to stderr and exits zero
so a configuration mistake cannot block a tool call. Argument errors skip capture.

Lifecycle publication from stats capture carries the native hook payload's
`session_id` into its HTTP provenance, even if no session variable was exported
or the environment retained an older session. This context lasts only for that
publication and is restored after success or failure. Missing identity remains
missing; the hook does not invent a session or change the process environment.
