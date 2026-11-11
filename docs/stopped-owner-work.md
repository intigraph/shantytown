# Work held by stopped owners

`SHANTY_STRANDED_WORK=off` is the default. `observe` admits the existing
fleet-tend owner's bounded stopped-work sweep; `release` separately admits its
revision-fenced releases. There is no new timer. Enabling either mode is an
operator rollout decision, not an effect of installing this source change.
Dry-run tend does not run these sweeps.
Each pass starts at most four remote intents and starts no further remote intent
after five seconds. It does not interrupt an in-flight write. Oldest observations
are served first. Complete local coverage accounting continues after the intent
budget ends, so a capped mutation pass cannot masquerade as an empty census.

The sweep requires a complete crew census and the selected tracker's complete
bounded assignee projection, including owned blocked/deferred work. The ranking
projection is insufficient because it omits owned waiting work. Inbox pointers
are excluded from the query and never unassigned: with thousands of open
pointers, hydrating them overflowed the bounded field budget and every pass
refused (aegis-byt). The census records `inbox_pointers` as not read rather
than a zero it never measured. Each pass writes the complete per-owner work and
operator-stopped release-due counts to
`<crew-root>/stranded-work/census.json`. A partial read refuses before mutation;
there is no generic board-list fallback. A card's explicit host must match the configured local host.
Remote or unscoped owners and failed/malformed process reads are UNKNOWN.
A current durable cycle refusal is separately measured as cycle-blocked, even
with a live pane; it is never described as process death. Malformed cycle
metadata is UNKNOWN. Otherwise only a successful process census proving a missing session or a foreground
login shell establishes down. Heartbeat expiry, old scrollback, quiet agents
and busy foreground subprocesses do not establish down. A missing card uses the same measured duration; missing preservation metadata still prevents release.

The first confirmed down observation starts a one-hour clock. After more than
one measured hour, every priority (including P0) raises persistent attention.
These inferred down/missing/cycle-blocked classes remain observe-only, including
when release mode is selected. Unknown evidence or a new launch generation
restarts the duration proof. Their deferred/decision/parked work stays untouched.

Release mode applies only to a recorded operator stop plus a successful local
process observation proving the owner down. A live or unreadable process cannot
be overridden by a stop file. This authoritative class gets immediate attention
and release-due accounting for ordinary and parked work in open, hooked,
in-progress, blocked and deferred states. ASK/desk-class items (an `ASK ` title,
an ASK label such as `desk`, `needs-stiwi`, `decision-needed` or
`blocked:human`, or a human blocker) are decisions held for a person, not
capacity: they stay with their owner and stay visible. Inbox recipient assignments
remain unchanged. Stop-record identity is part of the generation rechecked
under the lifecycle lock; relaunch or changed stop evidence prevents release.
Unassignment changes no title, notes, gate or deferral. In-progress work also
returns to open in the same revision-fenced write, because unassigned
in-progress work is on no plate and outside ready work. Open, blocked and
deferred work keep their status (aegis-byt). This class has its own pass bounds:
one keyed notice per stopped owner and stop generation (at most 10 per pass),
and up to 40 releases within 60 seconds. A whole stopped harness therefore
drains in one pass, not one item per two intents. Within this class work is served in
priority order (P0 first), so the cap never leaves ready P0/P1 work behind
parked lower-priority work. Notice bodies start with
their marker, which is what every receipt reader matches; a body that does not
would read back UNKNOWN and permanently refuse release. A dated stop
can be recorded with `st agent stop NAME --resume-at ISO8601`; this requires a
future timestamp with timezone, and cannot be combined with `--after-turn`.
Existing undated stop records remain readable.

Attention persists in `<crew-root>/stranded-work/attention.json` until the item
is parked, reassigned, closed or its owner is observed live. An acknowledged
error message does not clear attention. Each episode has one keyed durable
ERROR to the host's live administrator, even if the owner's lead is stopped.
Missing/ambiguous lead routing refuses and leaves attention retained. Previous
episodes are archived before replacement. Unknown delivery is never resent
automatically and prevents release pending operator reconciliation.

Confirmed down observations also use the existing opt-in owned-work graph
publisher and its held-work brief reader. The existing reader joins lifecycle
facts to owned work and retains expired evidence visibly as UNKNOWN. This is
the persistent brief attention surface; it requires that deployment's normal
publisher and reader binding. Installing this source does not enable the graph
publisher or prove live brief delivery. Private checkpoint bodies are not
published. Operator stop intent is not cleared by a process observation.

Release takes the same per-owner lifecycle lock as launch, stop and cycle,
then reads the exact item revision and rechecks process/intent evidence after
checkpoint metadata acquisition. A sanctioned concurrent launch is serialized;
an item change is fenced by the server revision. The Seeds adapter sends one
`update --assignee= --if-revision=REV
--transition-comment=COMMENT` transaction. The comment names the original owner,
first confirmed down time, retained workspace, branch or detached commit,
and original item notes/comments as the checkpoint pointer. Trees, branches,
notes and comments are never removed. Missing workspace/ref metadata refuses
release. Unsupported trackers have no generic-update fallback.

An exit-4 conflict means nothing was written. Other failed/indeterminate
releases retain their intent on disk and cannot be automatically retried.
Success requires exact item and atomic-comment read-back and preservation of
every other original field except the revision and modification timestamp. Operator recovery
must reconcile the retained marker against the selected board before admitting
another write. No deletion, process launch, unassignment inventory or live
sweep is performed by the offline tests.
An uncertain release also refuses a new launch for that owner: otherwise a
timed-out request could commit after the new process starts. Reconciliation of
the retained revision/marker is required before that lifecycle hold is cleared.

Rollback is to disable this opt-in sweep through the normal managed rollout
and revert its source through the reviewed lane. Existing attention/audit files
and preservation comments remain evidence. Reassigning any already released
item is a separate explicit, revision-aware decision; rollback never guesses
an old owner or deletes a worktree.

## Local stopped-owner delivery receipts

The local owned-work outbox saves a returned receipt ID in its existing
`attempting` record before reading metadata. A later process recovers that ID
with an exact receipt read, including a receipt already closed by its recipient.
Failure of that point read stays UNKNOWN; it never falls back to history or
permits a second send.

If a delivery reply was lost before its ID could be saved, the native Seeds
reader selects only identities matching that event's opaque marker. The query
has a three-row ceiling; multiple matches, reaching the ceiling, malformed
metadata, or incomplete transport refuse reconciliation. A unique result then
uses the same exact metadata reader. Closed receipts remain eligible. Other
receipts' descriptions and comments are never hydrated for this lookup.
A positively selected legacy store uses its SDK recipient-and-marker filter
with the same three-row ceiling and explicit completeness checks. An unavailable
reader remains UNKNOWN rather than enumerating all recipient history. Adapters without the optional point-reader capability
retain their declared adapter behavior; no cross-adapter cost claim is implied.
This source change does not enable a lifecycle publisher or admit a runtime
measurement cohort.
