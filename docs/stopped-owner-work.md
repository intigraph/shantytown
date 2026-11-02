# Work held by stopped owners

`SHANTY_STRANDED_WORK=off` is the default. `observe` admits the existing
fleet-tend owner's bounded stopped-work sweep; `release` separately admits its
revision-fenced releases. There is no new timer. Enabling either mode is an
operator rollout decision, not an effect of installing this source change.
Dry-run tend does not run these sweeps.
Each pass starts at most four remote intents and starts no further work after
five seconds. It does not interrupt an in-flight write. Oldest observations
are served first; untouched evidence stays unchanged when the budget ends.

The sweep requires a complete crew census and the selected tracker's complete
bounded active/deferred owner projection. It never falls back to an unbounded
board listing. A card's explicit host must match the configured local host.
Remote or unscoped owners and failed/malformed process reads are UNKNOWN.
A current durable cycle refusal is separately measured as cycle-blocked, even
with a live pane; it is never described as process death. Malformed cycle
metadata is UNKNOWN. Otherwise only a successful process census proving a missing session or a foreground
login shell establishes down. Heartbeat expiry, old scrollback, quiet agents
and busy foreground subprocesses do not establish down. A missing card uses the same measured duration; missing preservation metadata still prevents release.

The first confirmed down observation starts a one-hour clock. After more than
one measured hour, every priority (including P0) raises persistent attention.
Only OPEN items may be repooled; IN_PROGRESS items stay assigned for administrator
attention. There is no P0 bypass. Unknown evidence
or a new launch generation restarts the duration proof. Deferred items,
decision/blocked/parked labels, unknown priority, and deliberate undated operator stops or stops carrying
a future resume date are exempt. Malformed dates refuse release. A dated stop
can be recorded with `st agent stop NAME --resume-at ISO8601`; this requires a
future timestamp with timezone, and cannot be combined with `--after-turn`.
Existing undated stop records remain readable.

Attention persists in `<crew-root>/stranded-work/attention.json` until the item
is parked, reassigned, closed or its owner is observed live. An acknowledged
error message does not clear attention. Each episode has one keyed durable
ERROR to the host's administrator (the deployment's attention lead).
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
`update --status=open --assignee= --if-revision=REV
--transition-comment=COMMENT` transaction. The comment names the original owner,
first confirmed down time, retained workspace, branch or detached commit,
and original item notes/comments as the checkpoint pointer. Trees, branches,
notes and comments are never removed. Missing workspace/ref metadata refuses
release. Unsupported trackers have no generic-update fallback.

An exit-4 conflict means nothing was written. Other failed/indeterminate
releases retain their intent on disk and cannot be automatically retried.
Success requires exact item and atomic-comment read-back. Operator recovery
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
