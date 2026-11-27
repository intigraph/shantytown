# Ephemeral agents

`st agent spawn --ephemeral` starts a short-lived, supervised agent for one job:
review a PR, merge a PR, triage a red CI run, or do one small task. The
administrator or a lead manages these agents, and they report back to the
administrator. This is step 3
of the GitHub → quipu → chaski → st pipeline (aegis-c01c). chaski's routing
rules call this command; the administrator or a lead can also run it by hand.

## Why polecats were retired, and what is different here

Gas Town had ephemeral workers ("polecats"). They were retired under the
CREW-ONLY rule, partly because a spawned worker could escape supervision. It
could outlive its job, spend without limit, merge on its own authority, or
disappear without anyone being told. Each rule below closes one of those gaps.

| Gap                         | Rule here |
|-----------------------------|-----------|
| No owner                    | The card's `reports_to` is the administrator, and only the administrator or a lead (or a human shell) may spawn, stop or retry (leads admitted by aegis-za4f; a worker is still refused). Scoped recruitment and the recruit controller keep the administrator-only boundary. An ephemeral agent cannot spawn another one. The check does not depend on `$SHANTY_AGENT`, which a pane can unset: a process whose working directory is inside a live job's workspace, or that descends from a job's tmux pane shell, *is* that job. |
| Unbounded life              | Every job has a deadline (`lifetime_minutes`). The agent's Stop hook and every `st fleet tend` pass enforce it. Neither one is an agent poll. |
| Unbounded spend             | A turn budget (`max_turns`) and a context budget (`max_context_k`) are checked at every Stop. The agent counts in the usage governor like any card and carries the `first` survival band, so a governor tier sheds it first. |
| Unbounded fan-out           | `max_agents` caps how many ephemeral agents can be live on a host at once. The fleet governor's lane cap and its tier exclusions apply too. Over cap, a fresh `--ephemeral` spawn is **queued as a visible ticket** (`--list`, `st crew`) and launched when a job ends; retries, recruitment and `max_agents = 0` are still refused. See [The spawn queue](#the-spawn-queue). |
| A slot spent on a foreign forge | Review and merge jobs read the PR through `gh`, so they work on GitHub only. Before anything is read, locked, cut or launched, spawn resolves the `--repo` forge from the origin of the checkout the job would be cut from. A non-GitHub host is **refused** in one line naming the forge (route the PR to a crew reviewer instead); no slot is spent and no worktree is left behind (aegis-maw). Task jobs are not checked, and an unresolvable origin admits as before. |
| Silent exit                 | Every ending writes a result to the ledger, comments on the work item and sends one `ephemeral-result` event to whoever is waiting on it: the **spawner** (`spawned_by`) when that is a live lead, worker or keeper, with a live wake typed into its pane as well (an st-signed pointer built from the ledger, typed once per job; the job agent's summary stays in the event and is never signed), because an idle spawner never stops again to drain the event (aegis-0dh5: a lead sat idle 56 min while her own job's DONE went to the administrator). The administrator gets it when it spawned the job, or when the spawner is unknown, retired, not crew or down; that fallback event is marked risen and names why. That includes a clean report, a timeout, a budget hit, a dead pane, an undelivered job and a manual stop. The event is keyed, so a retried report is never sent twice. The administrator's drain renders it as a **finished job** (verdict + item), never as a stopped crew member to re-dispatch. An ephemeral agent's per-turn stops send no crew stop event at all. |
| Unfed panes                 | The job prompt is the agent's verified first turn. On macOS, hook verification is always "cannot tell" because there is no `/proc`, so an ephemeral job is delivered anyway; the deadline does not depend on hooks. Delivered means the job's turn STARTED, not that its text landed: on Claude Code st checks the composer is empty, types the job with no Enter, waits to see it in the box (a long job shows as `[Pasted text #1 +N lines]`), presses Enter as its own keystroke and waits to see the turn start (busy marker, spinner, context-left drop or the job echoed). It presses Enter again, up to three times, only while the box holds just the job, and never on text it did not type. A pane whose job did not start is ended at once as `launch failed`, with the reason. |
| Respawned zombies           | `st fleet tend` never respawns an ephemeral card. When the pane is dead or past its deadline, tend reaps it instead. The reap runs first in every tend pass, before any early return for a hold or a registry error. A job is `launching` until its job is delivered; tend leaves a launching job with no pane alone for `LAUNCH_GRACE_S` (10 min), so a pass mid-spawn cannot orphan the pane. |
| Mistaken for crew capacity  | Rule Zero / `free_feedable_workers` skip ephemeral cards, so a coordinator is never told to dispatch board work to one. |
| Merging around the lane     | A merge job holds its repo's serialized merge lane for its whole life: one merge job per repo at a time, with `merge_spacing_minutes` between them. It merges only through `st agent spawn --merge --head SHA`. That command checks in code, against fresh forge reads, that the caller is a live merge job (review, triage and task jobs are refused) and that the PR is its own. It also checks that the head equals the verified SHA and the head the item pins, the PR is not a draft, the author is crew (never an outside contribution), there is a non-author approval on that head (a GitHub APPROVE, or a signed Quipu verdict record from an agent other than the author agent; see [Signed verdicts](#signed-verdicts-one-github-account)) unless Quipu's stored query `repo_review_mode` says that repo's review mode is `none` (a missing fact, an unknown value or an unreadable query is `non-author`: fail closed; a policy change is a graph write, never a deploy), and no outstanding change request, and every check run is green. Only then does it call `gh pr merge --match-head-commit`. The agent's own gh credentials remain the residual gap. |

## Signed controller launch bridge

`recruit_launch.launch` is an internal controller library, without a CLI flag,
listener or runtime wiring. `recruit_channel.launch_connected` consumes one fresh
signed envelope from a trusted controller-owned connected Unix stream, checks
the protected sender UID and invokes that same native spawn bridge. It shares
the preparation channel's size/deadline bounds; it never accepts a prepared
receipt as an execution request. Late/lost replies preserve the attempt and
possible live job, so callers reconcile rather than resend. Neither entry
installs a socket endpoint or starts a listener.
`ephemeral.recruitment_launch_ready` defaults to
false and is separate from the protected UID gate. Enabling it belongs to the
deployment's runtime activation decision; this source does not enable it.
The ordinary scoped-recruiter CLI still refuses live launch and never borrows
the controller's privilege path.

The library accepts a fresh signed review-launch envelope and controller-owned
context, not a prepared receipt. It verifies independent controller authority,
consumes the protected persistent nonce and candidate claim, then enters the
existing spawn transaction. That transaction retains its planner, cap,
governor, job tools, worktree trust, ledger-before-card-before-launch and startup
delivery checks. It preserves the exact signed PR head for a review.

Protected key binding, custody, forge/check/verdict admission, expiry, quiet-time
and maintenance holds, governor and selected capability are checked again
before the ledger and at the existing launch seam. A final refusal uses the
existing end path. The receiver requires a matching live native ledger before
recording `launched`; a return code alone is insufficient. `refused` and
`unknown` attempts remain terminal. A crash or lost launch response retains the
nonce and candidate key; recovery never assumes that no job started.

This does not install keys or UIDs, select an endpoint, start a listener,
enable recruitment or accept merge verbs. Connected preparation remains
non-executable. Source tests use synthetic enrollment, forge and launcher
fixtures with real signatures, SQLite state, planner, ledger and cards; they
do not prove a deployed event-to-review launch.

## Lifecycle

### Review report to enqueue Action (default OFF)

The protected mailbox reaper hands a verified APPROVE to
`review_enqueue.report` before reporting and teardown. The handoff is disabled
unless `[ephemeral] review_enqueue_enabled = true`; missing or malformed config
never enables it. Enabling this handoff also retires new `merge` job admission
and the legacy `st agent spawn --merge` command, including for a merge job
launched before adoption. Both refuse before any forge read or merge attempt;
existing job reporting and teardown remain available. A malformed configuration
refuses the legacy command rather than falling back to defaults. With the flag
OFF, the existing merge lane remains available until the native adapter and
runtime acceptance qualify the replacement. No flag is changed by this source
update.

The controller also configures `review_enqueue_command` as an absolute adapter
argv. There is no default executable and no shell expansion. The review cannot
choose this command, its arguments, authority, state directory or receipt path.
This slice supports the protected GitHub review rail only. Activation requires
an installed native adapter that rechecks exact head, CI, signed review,
revocation, and the shared service order/hold gates before enqueue. A test
adapter is not native admission or runtime acceptance.

`EnqueueAction` sends one JSON stdin object with schema
`review-enqueue-action/v1`, intent ID, consumed attempt token and retained
candidate. The adapter must return exactly schema, intent, attempt, state
(`queued`, `refused` or `unknown`) and a bounded nonempty native receipt reference.
A wrong identity, timeout, nonzero exit or malformed reply preserves UNKNOWN;
no duplicate report retries it. The Action never issues a merge verb.
An Action failure is reported separately and does not prevent job teardown.

The controller must provision `<root>/ephemeral/review-enqueue` as its own
private directory, outside the job UID's writable ancestry. Only a controller
may supply the configured root and forge authority, protected job specification
and UID-validated report. The store independently verifies the enrolled,
signed exact-head APPROVE through `job_review.confirmed` before retaining an
intent. An intent pins authority, repository, PR node/number, head, reviewer,
signer, graph and review record. Repeated delivery returns that same intent;
job teardown does not remove it.

An intent starts `pending`. `begin` durably consumes one attempt before a
future native adapter may mutate the remote; `finish` records `queued`,
`refused` or `unknown` with its matching attempt token and receipt reference.
A crash in `attempting`, an unknown result or a terminal refusal cannot reset
to pending. Reconciliation is a separate operation; there is no automatic
retry, cleanup or repair. Prepared files left by a crash block new custody
until operator reconciliation. Capacity failure preserves existing evidence.

Custody proves past review verification, not permission to merge. Native
receipt compatibility, fresh revocation/head/CI checks, the shared
versioned per-service order/hold gate across every admission producer, and a
real approve-to-merge acceptance are still prerequisites for enabling this
handoff or retiring merge recruitment. No deployment config is enabled by this source change. There is no scheduler
or signing-key enrollment in this handoff.

```
spawn ─► admit (authority, cap, governor, merge lane) ─► ledger "live" + card
      ─► worktree (st repo worktree machinery, own branch) ─► _launch (the ONE launcher)
      ─► job prompt delivered as the verified startup turn
      ─► agent works … each Stop: turn/context/deadline check
      ─► `st agent spawn --report --verdict V --summary S`
            (or deadline / budget / dead pane / --stop)
      ─► result: ledger + item comment + stop event (and live wake) to the spawner, else the administrator
      ─► teardown: card removed, tmux session killed, worktree removed iff unchanged
```

The ledger lives at `<root>/ephemeral/<name>.json` and is the source of truth.
The card in `<root>/crew/<name>.json` is an ordinary worker card, so the census,
the governor, `st crew` and the launch path all see the agent with no special
cases. Teardown deletes the card **before** it kills the pane, so a tend pass
can never find a dead pane with a live card and respawn it. A worktree that
holds commits or uncommitted changes is **kept**, and the result says so,
because discarding an agent's output is the data-loss class `cleanup_worktree`
exists to refuse. A kept tree still loses its gitignored cargo `target/`
directories (rebuildable debris, about 30 GB of fleet disk at one count): only a
directory git reports as wholly ignored, named `target`, carrying cargo's
`CACHEDIR.TAG` or sitting next to a `Cargo.toml`, and reached without a symlink is
deleted. Tracked files and untracked files that are not ignored are never
touched. When this happens the outcome reads `kept (holds work): … ; cleared N
ignored cargo target/`.

Worktrees provisioned later by `st repo worktree` or `st go --worktree` for an
active job are recorded in its ledger before creation. Teardown checks these
alongside the spawn workspace, once per destination. Clean trees on the job's
original branch are removed; tracked changes, untracked output, ahead commits,
a changed branch or an uncertain Git identity keep the tree. Per-tree outcomes
are retained in `worktree_teardowns`. Provisioning after a job ends is refused.

Names are generated as `eph-<job>-<6 hex>`. Each agent has its own worktree on
branch `wt/<name>` when `--repo` names a checkout. A review, merge or triage
job without `--repo` gets a scratch directory under the ledger; a task job
without `--repo` is refused (below).

## Jobs

| Job      | Default harness | Prompt contract |
|----------|-----------------|-----------------|
| `review` | codex (fleet directive: reviews on codex) | Independent, non-author review of `--repo/--pr` at the exact head. Post one verdict comment on the PR (APPROVE / REQUEST CHANGES with findings), then `--report --verdict V --head SHA --evidence URL`; st signs the verdict into Quipu. Never push, never merge. |
| `merge`  | claude | Only through the serialized lane, and only the head the item pins (`--head`, or the `revision` of the chaski work request in the item). Verify green CI and, unless the repo's Quipu review mode is `none`, a non-author approval at that head, then merge through `st agent spawn --merge --head SHA`. Never push to the base branch, never `--admin`, never bypass protection. If anything is unproven, report `blocked`. |
| `triage` | claude | Find the cause of a red check. Comment the diagnosis on the item. Attended jobs may propose a fix on a branch and PR, never onto main. Protected UID jobs receive the read-only alert-triage instructions below. |

Protected triage jobs (a controller ledger record with `uid_binding`) investigate
one alert and report once on its original item, then exit. Their instructions
forbid ACKs, silences, restarts, configuration or code changes, publication, and
other runtime actions. Missing evidence or access produces a blocked report;
the job never borrows the controller's credentials. This narrower prompt does
not establish OS or endpoint capability isolation. Protected delivery, own-key
permissions, native negative probes, and host admission remain prerequisites
before enabling unattended launches. This change does not enable that gate.
| `task`   | claude | Do the item's acceptance criteria in the worktree. Open a PR if code changed. |

`--harness` overrides the default. `[ephemeral.harness_by_job]` changes the
defaults per deployment.

`[ephemeral.model_by_harness]` names the model a job runs on each harness
(aegis-jsp0). Spawn copies it onto the job card, so the launch passes `--model`
and exports `SHANTY_MODEL` from that one value, and the job's Quipu writes carry
`X-Quipu-Model`. A harness with no entry gets no model: the harness default runs
and nothing is declared, so write provenance stays visibly partial.

## Administrator surface

```
st agent spawn --ephemeral --job review --item aegis-x --repo owner/name --pr 12 [--checkout PATH]
st agent spawn --list [--json]          # live + recent jobs and queued tickets (also in `st crew` and the admin's `st anchor`)
st agent spawn --ephemeral ... --priority 0   # over cap: queue priority, 0 highest (default: the item's)
st agent spawn --ephemeral ... --track ops    # work track for queue shares: ops | short-term | roadmap | backlog (default roadmap)
st agent spawn --drain [-n]             # launch queued tickets into free slots (the end paths run this)
st agent spawn --drain-events FILE [-n] # one spawn per unseen chaski pr-lifecycle event (below)
st agent spawn --pool status|size N|pause|drain|resume   # see and manage the pool (below)
st agent spawn --stop eph-review-1a2b3c # result "stopped", report, teardown
st agent spawn --stop q-3f9a1c2b4d5e    # cancel a queued or claimed ticket: moved aside to ephemeral/queue-removed/
st agent spawn --retry eph-review-1a2b3c   # new agent, same job, attempt+1 (max 3)
st agent spawn --ephemeral --job merge --item aegis-y --repo owner/name --pr 12 [--head SHA]
st agent spawn --report --verdict done --summary 'Nonempty result'   # run BY the ephemeral agent
st agent spawn --report --verdict approve --head SHA --evidence URL --summary 'APPROVE: findings'   # a review job
st agent spawn --merge --head <sha>     # run BY a merge job: the guarded merge
st agent spawn --reap                   # the sweep tend runs; by hand for a dry look with -n
```

Run the report command directly with one quoted summary argument. In attended
Codex jobs, heredocs, pipes and shell wrappers can fail to match the report-only
permission and leave the ledger read-only. An empty summary is refused before
publishing a verdict or ending the job. Existing stdin reports remain supported
for callers that can supply stdin without wrapping the command.

## The spawn queue

aegis-cui. Before it, a spawn over the cap was refused and the work was lost
unless a human retried it. Now a fresh `st agent spawn --ephemeral` whose ONLY
refusal is the cap writes a ticket and exits 0:

```
  QUEUED q-3f9a1c2b4d5e: task on aegis-x (P2), position 1; over cap: 2/2 ... It launches when a job ends
```

`--dry-run` prints `would queue ...` and writes nothing. A ticket records the
job kind, item, repo/PR/checkout, harness, track, priority, requester and
`enqueued_at`, one JSON file per ticket under `<root>/ephemeral/queue/`.
Every other refusal (authority, no administrator, merge lane, governor,
`max_agents = 0`) still refuses, as do `--retry` and scoped recruitment.

**Drain on job end, no poller.** Every end path frees its slot and kicks the
queue: `--stop` and the reaper after their synchronous teardown, `--report`
from its detached teardown once the pane is gone. The drain
(`st agent spawn --drain`, started in its own session) claims the
highest-priority (0 first, unranked last), oldest ticket and runs it through
the full spawn path as its requester, so authority, governor and trust checks
apply again at launch. A ticket whose item is closed or no longer exists is
dropped, never launched, and kept with its reason under `queue/dropped/`; an
item the tracker cannot read keeps its ticket queued. A ticket the spawn
refuses at launch is dropped the same way with the refusal as its reason.
A ticket whose launch raises instead of refusing is dropped the same way
(`launch crashed: <error>`) and the drain goes on to the next ticket: one bad
ticket never ends a drain (aegis-za4f.16). Tickets dropped in the last 24h show
on `--list` as `failed` with their reason.
A retry's superseded job does not drain: that slot is the retry's.

## PR lifecycle events from chaski

aegis-za4f.21. Every PR step (review a new head, fix REQUEST-CHANGES, merge at
green and approved) used to wait for the administrator to notice and spawn it
by hand; on quipu#1354 that produced a merge job before CI was green and an
approval for a stale head. Chaski's `pr-lifecycle` emitter now appends one
JSONL line per needed action, and `st agent spawn --drain-events FILE` (run by
chaski or a timer, as an administrator or lead) recruits the job:

```
{"event_id": "<sha256 of repo|pr|head|job>", "repo": "intigraph/quipu", "pr": 1354,
 "head": "<40-hex>", "job": "review|task|merge", "item": "<id or null>",
 "reason": "new-head-unreviewed|changes-requested|green-and-approved|ci-red",
 "observed_at": "<UTC>"}
```

Each unseen event becomes exactly
`--ephemeral --job J --item I --repo R --pr N --head H --track roadmap`, through
the same path a typed spawn takes, so the cap, the governor, authority and the
merge job's own re-verification all apply. It is a local consumer of a file,
not the signed controller `recruit_*` path.

- **Idempotent on event_id.** Settled events are appended to
  `<root>/ephemeral/pr-events.jsonl` and never offered again. An `event_id`
  that is not `sha256(repo|pr|head|job)`, or any malformed field, skips that
  line with its reason; the rest of the file still drains. The first sighting
  of a bad line exits 2 and is recorded by the sha256 of its text. Later drains
  still print it but exit clean, because an append-only file keeps the line
  forever.
- **Admitted** (settled): launched, or QUEUED over the cap. The ticket then
  carries it, as for any queued spawn.
- **Superseded** (settled): the file holds a newer head for that PR, so the
  step is stale. The new head's own events re-arm it. "Newer" means later in
  the file, so the emitter must append lines in observation order. A line
  appended out of order supersedes the newer head before it.
- **Pending** (offered again next drain, exit 2): the spawn refused (governor,
  pool, authority, a merge pin mismatch) or crashed, or the event names no item
  to report on. A refusal is not dropped: the first one is dated in the ledger.
- **Expired** (settled): still pending 24h after its first refusal
  (`pr_events.PENDING_TTL_S`). It is printed and recorded, then never offered
  again, so a permanent refusal (a pin mismatch, a closed PR) cannot hold exit 2
  forever. A new head re-arms the step.
- **Already in flight** (settled as admitted): a live job or queued ticket
  already has this job, repo and PR, and either the exact head (merge records
  keep it) or, for head-less review and task records, a spawn or enqueue time
  at or after the event's own `spawning` intent line. This covers a drain that
  crashed after the spawn but before it settled; the spawn path does not refuse
  a duplicate itself. A job spawned before the attempt, such as a hand-spawned
  task on an older head, never matches, so it cannot settle a new head's event.
- A `merge` event whose reason is not `green-and-approved` is refused as an
  emitter bug. `--dry-run` prints the spawns and settles nothing.

**Bad checkout refused at admission.** An explicit `--checkout` that does not
exist, is not a git checkout, or has no remote naming `--repo` (owner/name, any
host) is refused before a ticket is queued or a worktree is cut. A GitHub remote
that still uses a repo's pre-move slug (`git@github.com:scbrown/tambo.git` for
`intigraph/tambo`) is admitted: on a raw mismatch, both `--repo` and each GitHub
remote are mapped through the forge's canonical name before comparing. A forge
that cannot answer leaves the mismatch refused, and the refusal says so.

**Cancel.** `st agent spawn --stop <ticket>` moves a queued or claimed ticket to
`<root>/ephemeral/queue-removed/<ticket>.json`, rewritten as an unclaimed queued
ticket with `cancelled_at`/`cancelled_by`. Moving the file back into `queue/`
requeues it. A claimer already past its ledger write still launches its job;
stop that job by name.

**Crash semantics: exactly-once launch, never lost.** The claim marks the
ticket with the drainer's pid. The spawn writes the ledger record carrying
`ticket` and deletes the ticket file in the same `lock()` step. The next claim
first recovers: a claimed ticket a ledger record names is settled, never
relaunched; one with no record whose claimer is dead (or older than
`LAUNCH_GRACE_S`) goes back to queued with its age ONCE (`MAX_RECOVERIES`); a
second dead claim drops it with its reason, so a ticket that kills its claimer
cannot block the queue or show `(launching)` forever. A launch that dies after
its ledger write is an ordinary LAUNCHING job the reaper already ends.

### Routing by harness and track

aegis-fye. Slice 1 drained into ANY free slot. Two routing rules now apply at
drain and at admission; both are OFF unless configured, and with neither
configured the drain order is slice 1's exactly (priority, then age).

- **Harness.** A ticket only launches into capacity for its own harness.
  `[ephemeral.max_agents_by_harness]` caps each harness; a harness with no
  entry is capped by `max_agents` alone, and `max_agents` still bounds the
  host total. A spawn over its harness's cap queues like any over-cap spawn,
  so a codex ticket waits while claude capacity is free (and is not taken by
  a claude ticket's slot either). A harness capped at `0` is off: its spawns
  are refused, never queued, because nothing could ever drain them.
- **Track.** Every ticket and job carries a track (`--track`, default
  `roadmap`). With `[ephemeral.track_shares]` set, the drain picks the track
  furthest below its share of live jobs, then priority, then age. Shares are
  weights (normalised to their sum); a track with no entry has share 0.

`--list` shows harness and track on each live job and ticket;
`--drain --dry-run` prints the routed launch order.

Not yet: the Codex overflow trigger (aegis-za4f.14).

### Pool management

aegis-za4f.3. The administrator (or a lead) sees and manages the pool at
runtime without editing `shantytown.toml`:

```
st agent spawn --pool status        # size, live/size, paused|draining, per-harness and per-job use, queue, TTL breaches
st agent spawn --pool size 4        # runtime pool size, replacing [ephemeral] max_agents
st agent spawn --pool size config   # back to the toml cap
st agent spawn --pool pause         # nothing launches; fresh spawns still QUEUE (no work lost)
st agent spawn --pool drain         # nothing launches and fresh spawns are REFUSED; live jobs finish, queued tickets are held
st agent spawn --pool resume        # clear pause/drain and kick the queue
```

The state is one file, `<root>/ephemeral/pool.json`, written under the ledger
lock. A missing or unreadable file is the config's pool, so a corrupt override
can only fall back. A runtime size never switches on a host whose config says
`max_agents = 0`. `status` is a read anyone may run, like `--list`; every
change needs spawn authority. `resume` and `size` kick the queue the same way
a job end does, so there is still no poller. `pool` is a mode of `spawn`
rather than a new leaf command under `st agent`, because the command surface is pinned
(`shantytown/surface.py`).

**Per-job concurrency.** `[ephemeral.limits.<job>] max_concurrent = n` caps
live jobs of one type. Over it, a spawn queues like any over-cap spawn, and
the drain skips that job's tickets while other job types launch.

**Queue TTL.** `[ephemeral] queue_ttl_minutes` (default 240, `0` = off). A
ticket queued longer than that is reported once, by the `st fleet tend` reap
sweep: a stop event to the administrator (`ephemeral-queue-ttl`) and a comment
on its item. It is marked `OVERDUE` on `--list` and **stays queued**, because a
TTL makes a stuck queue visible and never throws work away. If neither report
leg lands, the ticket stays unmarked and the next sweep tries again, so a
breach is never silent.

**Disk floor** (aegis-xa6w). `[ephemeral] disk_floor_gb` (default `0` = off) is
the free space, in GB, the filesystem worktrees land on must keep. That path is
`disk_path` when set, else the mounted worktree storage root, else the st root.
With no worktree storage configured, worktrees land beside their checkout
(`<repo>-wt`), which can be a different mount from the st root: such a host must
set `disk_path`. The governor line names the path it read, so a wrong one shows.
A worktree storage file that exists but is invalid reads `lost` (held), never
the st root's filesystem in its place.
Below the floor a fresh spawn **queues** with the reason `disk below floor: <N>G
free on <path>, floor <F>G` and the drain launches nothing; it re-reads the disk
before every claim, so a drain stops at the floor it is filling towards. A full
disk is exactly when no job ends to drain the queue, so the `st fleet tend` reap
sweep kicks the drain once space is back. A floor whose filesystem cannot be
read (`lost`) holds like `low`. `st crew --governor` prints the line
`disk ok|low|lost <free>G free/floor <F>G/<total>G on <path>` (and `disk` in
its JSON) whenever a floor is set, and nothing when none is. Rollback: set
`disk_floor_gb = 0` and run `st agent spawn --pool resume` to drain anything it
held.

Teardown that **keeps** a job's worktree because it holds work also removes the
tree's git-ignored top-level `target/` build cache (never a symlink, never a
tracked directory); the reap sweep does the same, once, for jobs that ended
before this landed. The edits and commits are the work; a cargo cache of up to
8G per tree is not. This runs whether or not a floor is set.

## Configuration

```toml
[ephemeral]
max_agents = 2              # live ephemeral agents per host; 0 disables spawning
lifetime_minutes = 60       # hard deadline per job
max_turns = 40              # Stop-hook turns before the budget ends the job
max_context_k = 300         # context ceiling in k tokens
merge_spacing_minutes = 10  # minimum gap between merge jobs on one repo
unattended = false          # keep approval prompts; omission inherits the administrator card
require_verified_identity = false # opt in after protected UID migration
unattended_uid_ready = false # unattended gate: OFF until distinct job UID isolation is verified
recruitment_launch_ready = false # separate signed-controller gate; no runtime wiring
queue_ttl_minutes = 240     # report a ticket queued this long, once; it stays queued; 0 = off (aegis-za4f.3)
disk_floor_gb = 0           # free GB to keep on the worktree filesystem; below it spawns queue; 0 = off (aegis-xa6w)
                            # rollback: disk_floor_gb = 0, then `st agent spawn --pool resume`
disk_path = ""              # absolute path to watch; "" = worktree storage root, else the st root
                            # (set it when worktrees land beside checkouts on another mount)

# Signed review verdicts (aegis-c01c.7). All empty = off.
verdict_graph = ""          # registered Quipu graph IRI the records go into
verdict_signer = ""         # verifier key id; default st-review.<host>
verdict_key = ""            # default $XDG_STATE_HOME/shantytown/verdict-signer.pk8
lane_release = []           # e.g. ["chaski-github-work", "--config", "/etc/chaski/github-routing.yaml"]

[ephemeral.harness_by_job]
review = "codex"

# The model each harness's jobs run and declare (aegis-jsp0). Unset = none.
[ephemeral.model_by_harness]
claude = "claude-opus-5-5"

# Per-harness slot caps (aegis-fye). Unset = max_agents for that harness; 0 = off.
[ephemeral.max_agents_by_harness]
codex = 1

# Queue drain shares per track (aegis-fye). OFF unless this table exists. The
# quarter plan's split (ephemeral.SUGGESTED_TRACK_SHARES):
[ephemeral.track_shares]
ops = 20
short-term = 15
roadmap = 50
backlog = 15

# Per-job-type bounds (aegis-za4f). A job type without an entry keeps the
# global lifetime_minutes / max_turns above.
[ephemeral.limits.task]
lifetime_minutes = 90
max_turns = 40
max_concurrent = 1          # live task jobs at once; over it, spawns queue (aegis-za4f.3)
```

### Attended Codex task jobs

A task job edits source, so it needs more than a review's sandbox:

- **Worktree.** `--repo owner/name` (with `--checkout <path>` for a
  non-default clone) cuts the job's worktree from that checkout. A task job
  whose named repo resolves no local checkout is refused; it never falls back
  to a scratch dir. A task job with no `--repo` at all, including one given
  only `--checkout`, is refused before any request is built, so over cap no
  repo-less ticket is queued either: eph-task-9a5fba, 72e750 and 2g7f each got
  a scratch dir and spent their whole slot discovering they had no source
  (aegis-za4f.15).
- **Sandbox.** The job card is not `dangerous`, so its Codex daemon keeps
  `workspace-write`. That alone has no DNS (no tracker or Quipu), a read-only
  Quipu read-budget ledger and a read-only git common dir. The spawner writes
  `st-job-sandbox.json` into the job's own daemon home. The daemon then starts
  with `network_access=true` and exactly two writable roots: the read-budget
  ledger and the git common dir of the source checkout. It never gets
  `danger-full-access`. A tampered file refuses the launch.
- **git.** Task jobs may run git on their own branch. Pushing main/master,
  force pushes, branch deletion, reset, rebase, and `gh pr merge`/`gh api` are
  exec-policy `forbidden`. Branch protection on the forge stays the boundary
  for main.
- **Own item.** The prompt tells the job to `st work item show <item>`, so the
  rules allow exactly that command for the job's own item id, a literal token.
  Another item, a wildcard, and update/comment/close still need approval.
- **Kit.** A task job whose JobSpec resolves no MCP servers is refused at
  launch, so it cannot run without Quipu or code search.

`require_verified_identity` defaults to false while hosts migrate. In this
compatibility mode, an administrator's environment identity or a human shell
can manage jobs, and report/merge retain the existing workspace/ancestry and
matching environment checks. A job in its workspace or process tree remains
unable to manage other jobs even after clearing its environment identity.
This mode retains the session-detachment limitation of the old guards.

After the host has protected UID bindings, set `require_verified_identity = true`.
Then spawn, retry, stop/reap (including merge-lane release), report and merge
require the protected identity described in
[agent identity migration](agent-identity-migration.md). Environment and
anonymous fallbacks are refused. Report/merge require the authenticated job's
own identity, independent of cwd/ancestry. Read-only `--list` remains available.
An existing policy's authentication errors still fail closed in either mode;
this setting does not bypass a broken or mismatching protected binding.

The `unattended_uid_ready` flag is an operator readiness declaration, not a UID
installer or proof of isolation. Keep it false pending the distinct-job-UID
migration decision and verification. `unattended = true` or an inherited
dangerous administrator card alone cannot enable unattended jobs. Gate refusal
happens before a retry ends the old job or writes a new ledger/card/worktree.
This change creates no users and changes no system policy or host configuration.
The trusted code-side tend reaper can still finish expired jobs.

## Signed verdicts (one GitHub account)

Every crew PR and every review comes from one shared GitHub account, so a
non-author GitHub APPROVE never exists. The approval lives in Quipu instead,
as the record chaski #49 routes on (`shantytown/gate_verdict.py`):

- **Review job.** `st agent spawn --report --verdict approve|request-changes
  --head SHA --evidence URL` (the process must be the review job) writes an
  `aegis:GateApproval`: `aboutGitHubEntity` (the PR node `aegis:github.<node_id>`),
  `commitSha`, `outcome` (approve / changes), `by` (the job's agent name),
  `recordedAt`, `authorAgent` (from the PR's `authoredByAgent` fact),
  `evidence`, `evidenceHash`. Beside it goes an `aegis:Verdict` whose
  `targetRef` is that record, signed with quipu's v1 verdict signature
  (ed25519 over `v1|predicate|target|outcome|evidence_hash|tier|verifier`,
  quipu `src/signing.rs`). The evidence hash covers every GateApproval field,
  so an edit after signing voids it. A failed write is reported, never
  silent, and no merge can rest on that review.
- **Merge gate.** `st agent spawn --merge` reads the records on exactly the
  head, from the ONE configured `verdict_graph` (never any named graph), and
  recomputes each evidence hash. A record counts only if its signature
  verifies under a key pinned in `/etc/shantytown/verdict-signers.json`
  (root-owned, not writable by others; `{"version": 1, "signers": {"<signer
  id>": "<public key hex>"}}`), the signer id is not an agent of the PR, AND
  Quipu's `POST /verdict/verify` with the stored verdict's IRI says `trusted`.
  Quipu alone is not enough: any agent can currently write a
  `VerifierRegistration` and enroll its own key. Then
  chaski's rules: a verdict by the PR's author agent never counts, each other
  agent's latest word counts, any `changes` blocks, an unknown author agent
  approves nothing. An unsigned or forged record is ignored. A Quipu read
  failure is "not approved".
- **Merge job.** It merges only the head its item pins. When it ends without
  merging, its lane frees at once (spacing counts merges only) and, if
  `lane_release` is set, st calls chaski's `lane release` with the request id.
- **Authorship.** `st repo pr --create` records `<PR> aegis:authoredByAgent
  "<agent>"` so chaski and the gate can tell author from reviewer.

The signer is st on the host, not the agent: ephemeral agents get a new name
per spawn, so no human could register theirs. Key custody is quipu's v1
posture (a 0600 host file, generated on first use, untrusted until
registered), and the agent's Unix user can read it, the same residual gap as
its gh credentials.

**Enabling (not done here).** Register a committed graph for the records
and set `verdict_graph`. Run one review to generate the key, then have a human
pin its public key with sudo in `/etc/shantytown/verdict-signers.json` and
write an `aegis:VerifierRegistration` in ROOT (`aegis:verifier` = the signer
id, `aegis:publicKey` = the key's public half, `aegis:attests
"github-pr-gate-approval"`). Set `lane_release` when chaski's receiver runs.

## One Shuttle run per job (aegis-za4f.19.1)

Every job is one Shuttle workflow run, named after the job (`eph-task-…`).
`shantytown/job_runs.py` holds the definitions and the lifecycle:

- **start** once the ledger is written at spawn (`st-ephemeral-task-v1`, or
  `st-ephemeral-review-v1` for a review job), in state `spawned`;
- **claim** when the job's prompt is delivered (`mark_live`);
- **end** on the recorded result: a task that reports `done`/`merged` walks
  `work -> report`; a review walks its verdict (`approve -> report`,
  `request-changes`, `reject`); anything else, or a job that never claimed,
  is `fail`. `open-pr` (task) and `enqueue` (review) are legal edges no st
  path takes yet: nothing reports them to st, and the run never claims a step
  on the job's say-so.

Illegal steps are refused in st before any signer is asked, and again by
shuttle. The run is recorded on the ledger as `shuttle_run` (definition,
state, steps, signer, last error). Recording never blocks a job: a host with no
`shuttle`, no administrator, or a refused step still launches, reports and
tears down, and the entry says why it has no run. That holds for ANY failure,
not only a refusal: a run operation that raises anything (an unwritable
TMPDIR, a run lock it cannot open, a stale definition) records the error on
`shuttle_run` and returns, so `--report` still notifies and tears down.

**Signing is an interface.** `job_runs.Signer` is what the run needs
(`define/start/advance/verify`). The only implementation today is
`RegisteredKeySigner`: the `shuttle` CLI with `--require-existing-keys`,
signing as the job's administrator, whose key is already registered. No
per-job key is generated, injected, or passed in env, argv, a file or an fd
(2026-09-12 decision 3). The attribution caveat of that decision still holds
for this signer: the signature names the administrator's key, and a same-uid
job could read that key. The signing broker (sattler's ruling B on
aegis-za4f.19, slice S2) replaces this signer with per-job keys held under
its own uid, and callers do not change.

**S1 widens who exercises that key.** Before S1 the administrator's key signed
only the administrator's own transitions. Now `st agent spawn --report`, run
from inside the job's own process, signs the job's ending with it. That is the
same 2026-09-12 caveat applied to more callers, accepted until S2, not fixed.

**Bounds.** Each shuttle call has a 10s timeout, and one run operation (start,
one step, or the ending) has 20s in total. A hung shuttle therefore costs
`--report` at most 20s, and the ending is recorded as refused. One job's run
operations hold a per-job run lock (`.run-<name>.lock`) from the read through
the store, so a claim racing a timeout's ending cannot drop a signed step. Teardown removes the lock file.
The host ledger lock is never held across a shuttle call.

`SHANTY_JOB_RUNS=none` turns runs off. It is the negative control, and the
test suite runs with it so that no test appends to the operator's shuttle log.

## Known limits

- **One GitHub identity.** A non-author GitHub APPROVE can never exist, so the approval comes from a signed Quipu verdict record (above). Until verdict records are enabled and the signer is registered, merge jobs report `blocked`. That is the safe outcome.
- **OS isolation remains a prerequisite for unattended jobs.** Compatibility mode retains environment/ancestry restrictions and their detachment limitation. Opt-in verified identity survives session detachment. Shared Unix UIDs are not isolation; unattended launches stay gated until the separately governed distinct-UID setup is verified.
- **Shared settings.** A spawn never rewrites the shared role settings files. Only crew launches repair the StopFailure hook there. One exception: when the job's harness has *no* role file yet, spawn emits it, using the same emitter and provisioning as `st fleet roles set`. This happens, for example, on the first `--harness agy` or `--harness opencode` job in a store where no crew card runs that harness. Without it, every job on that harness refused with "could not materialize settings" (aegis-j550). An existing file is never touched.
- **Job tool profiles on opencode.** A bound JobSpec (`[ephemeral.jobs.<job>]`) is enforced for claude, codex and agy (`job_tools.prepare_settings`). An agy job gets its own canonical file (`settings/agy/job-<name>/settings.json`) whose PreToolUse gate runs inside agy's hook adapter on every MCP call, and its workspace MCP kit is replaced by exactly the selected servers. On opencode, a job whose kind binds one refuses at launch with "job tool profile is not supported by this harness". It does not run with the profile dropped, because that would widen its tool surface.
- **Task workspace consent.** Task jobs have no per-PR allowlist to restore. Provisioning records the hash of the exact workspace consent bytes it emits for that task, so the folder-trust guard can verify them. A later edit, a different workspace, or an unproven file still refuses trust; a completed job is not rebound by provisioning.
- **Job MCP kit.** The guard used to admit a job's `.mcp.json` when its server *names* were all in the kit, so a planted file that reused a kit name with its own command passed. Provisioning now records the sha256 of the exact `.mcp.json` bytes it publishes into an ephemeral job's own workspace (`kit_mcp_sha256`). The guard requires both conditions: the names are in the kit, and the bytes match that hash. A missing record, a symlink, or any later edit refuses trust (aegis-8et).
- **Hooks on macOS.** Stop-hook enforcement of the turn and context budgets needs the deployed `st` in the agent's pane. The deadline is enforced by tend regardless.

## Out of scope here

GitHub ingress (aegis-c01c.3), the chaski routing rules that decide *when* to
spawn (aegis-c01c.4), the stop-policy change that counts the administrator's
in-flight ephemeral work (aegis-c01c.1), and the tambo install/verify step
(aegis-c01c.5).

## Protected job launch capabilities (source staging)

The distinct-UID launcher uses an operator-owned capability per job principal,
not a username supplied by a model. `/etc/shantytown/jobs` on Linux, or
`/Library/Application Support/Shantytown/jobs` on macOS, holds reviewed manifests.
Each binds the exact request, harness, controller UID, dedicated job UID/GID,
private home/workspace/settings and pinned argv. Controller environment and
arbitrary command arguments are never forwarded. The installed helper must be
root-owned, run an isolated interpreter from a private immutable installation,
and be the only executable named in its narrowly scoped sudoers rule.

The first account may be named `_stjobs`; additional principals require unique
accounts and UIDs. A shared or recycled UID cannot preserve distinct job
identities. Existing protected identity bindings require UID/GID >=10000; macOS
account hiding must use the explicit hidden-account attribute rather than
weakening that floor. Each job needs its own enrolled credentials. There is no
controller credential copy or automatic key registration.

A readiness boolean alone does not admit a launch. Verified identity and an
unused matching capability are required before retry side effects. A native
helper check validates the protected actor binding and actual account, checks
private state, and probes privilege dropping in a short disposable child. The
real launch rechecks its immutable manifest, reserves the UID in a locked,
fsynced receipt, clears supplementary groups and inherited file descriptors,
drops root credentials, and executes only the prepared argv with an allowlisted
environment. A failed drop never falls back to the controller UID. Receipts and
job homes survive failures and rollback; a UID is not reused for another job.

A live unattended retry currently refuses and preserves its old lane, even
following a successful probe. Completed retries require a fresh capability.
This avoids claiming an atomic cross-UID handoff from a preflight observation.
Attended compatibility behavior remains separate.

This source staging is **not installed acceptance**. Keep both readiness and
verified-identity activation at their existing deployment values until the
reviewed provisioning and native acceptance packet is complete. Cross-UID
reporting and turn accounting use a staged mediated mailbox described below:
do not make the shared ledger writable or expose controller signing keys.
Tambo/macOS and Goldblum/Linux source provisioning, isolated metadata/config,
own-key review signing, native file/signal/identity denial proofs and rollout
authority remain required before enabling unattended jobs.

The staged protected helper also has a fixed `stop <principal> <digest>`
operation for the admitted controller. It verifies the exact consumed UID
receipt, forks, drops to that UID, and signals remaining processes by UID,
including processes outside the original session. Signals never run as root.
An unreadable process table, failed drop, permission failure or timeout leaves
termination unproven. Teardown then retains the card, workspace and occupied
lane; a supplied DONE record cannot override the controller ledger. Native
macOS/Linux qualification of this operation is still required.

The read-only launch probe now also performs the existing pinned identity
attestation from the job's own home after UID drop and environment clearing.
It must return the registered job principal. A username or successful UID
switch alone does not establish readiness. These staged paths have only been
qualified with private source fixtures; no privileged helper was installed or
executed as part of that qualification.

Operator preparation must include a root-owned `slots.json` next to the job
manifests. Version 1 has exactly `version`, `uid_min`, `uid_max`, and `slots`.
The range must start at 10000 or higher; `slots` maps each exact job principal
to its reserved `uid` and manifest `sha256`. Its entry count is the explicit
host capacity, bounded to 1024 by the source parser. There is no default host
range or automatic account growth. The actual count/range belongs in the
reviewed per-host rollout packet.

The protected manifest set must exactly equal this plan. Missing, extra,
changed, duplicate-UID or shared-account entries refuse, including when the
helper is invoked directly. Consumed manifests and UID receipts remain as
non-reuse records after cleanup or rollback. Adding capacity or changing a
reservation requires a separate operator-reviewed plan update; exhaustion
never falls back to another UID. This implements the selected per-job slot
architecture, while unattended readiness remains false pending native proof.

The fixed helper's `submit` operation admits only the manifest's job UID;
`poll` admits only its controller UID. Both require the exact protected binding
and consumed UID receipt. Jobs submit a bounded JSON result or turn token on
stdin, with a five-second input deadline. They cannot select a ledger path,
another principal, a command, or a signing key. A root-private mailbox retains
the first result, deduplicates turn tokens, and refuses conflicting retries,
corruption, exhaustion or interrupted writes. Jobs never open the controller
ledger through this path.

The source report handler queues the message before reading controller config.
The turn hook queues a turn; the controller's existing reaper drains messages,
applies monotonically increasing turn counts and performs ordinary notification
and verified UID teardown. A queue acknowledgement means the message is saved;
delivery and teardown are still pending. Job reports confer no signing or
merge authority. Until the job's own review signer is qualified, an unsigned
review message becomes a blocked result; no controller key substitutes for it.
These paths are staged source with private fixture coverage, not native
cross-UID acceptance or an installed deployment.

A launch manifest has separate `controller_root` and `root` paths. The former
identifies the controller's private store; launch qualification requires its
path to belong only to root/the controller and its directory mode to exclude
other users. The latter must be the job's own root-owned metadata store at
`/var/lib/shantytown/job-stores/<principal>`. Only that job root is passed in
`SHANTY_ROOT`; the controller root is not forwarded to the job environment.
The two stores cannot contain one another. The provisioning packet must build
the minimal public job metadata there without controller secrets. Lifecycle
stop/drain authorization uses immutable identity and the consumed receipt,
so changing job-owned settings cannot prevent the controller from stopping it.

The staged helper's fixed `prepare <principal> <digest>` operation builds that
minimal store only for its admitted controller UID and exact protected slot
manifest. It creates one public own-job card and a configuration with verified
identity required, zero spawn capacity, unattended admission disabled and UID
readiness false. No controller config, pane, credential, endpoint or signing key
is copied. Existing stores must match exactly; extra or changed files refuse.
Interrupted staging is retained for explicit recovery. Preparation does not
consume a launch slot, create an account or launch a job. Provisioning must grant
this exact operation separately; a job's submit-only rule never grants prepare.

Protected job stop hooks authenticate their UID before consulting environment
identity or controller pane/hold state. They submit a bounded own-turn receipt;
context depth is unknown when no own measurement is available. Failed identity
or receipt acknowledgement blocks further work. The controller remains the
budget and teardown authority. Launch rechecks the job's own attestation after
admission and before consuming its UID reservation.

The separate helper bootstrap uses a fixed private Python with `-BIS`: isolated
imports, no environment/cwd/user-site paths, no site or `.pth` execution, and no
generated bytecode that would change the pinned runtime tree. It requires the
private interpreter prefix rather than a system-library fallback.
Before importing application code it validates its interpreter/import paths
and the entire bounded package at `/opt/shantytown-job-launcher/app/shantytown`
as root-owned and non-writable, refusing symlinks. The reviewed installation
must provide regular immutable interpreter/application paths; an editable
checkout or ordinary user-owned virtualenv is not a supported helper install.
The bootstrap keeps only sudo's kernel-derived caller UID and fixed PATH/locale
for application imports. Native installation qualification remains outstanding.

The capability path validator accepts macOS's fixed root-owned `/var` alias
only when it resolves to `/private/var`, whose immutable ownership is checked
as well. This permits the existing protected-home convention on macOS without
accepting job-controlled symlinks or arbitrary aliases. Native macOS acceptance
is still required; the source fixtures simulate both accepted and refused paths.

Protected review slots can declare an explicit `review` policy in their pinned
manifest; other slots use `review: null`. The policy names the exact repository,
PR number, GitHub node, reviewed head, author, graph, verifier ID, public key,
and the job's private key path. The verifier ID is
`st-job-verifier.<job-principal>`, with a distinct key per slot. The key must
already exist, be private to the job UID, and match the protected public key.
No controller key, environment-selected key, automatic key generation or
registration is used by this path.

Operator pin-file version 2 supports these scoped entries alongside legacy
host keys. A scoped entry has `public_key`, `principal`, `repo`, `pr`, `pr_node`,
`head`, and `author_agent`. Its signature counts only for that exact reviewer
and PR/head, with independently readable matching authorship. A bare job-key
pin or a key duplicated under another signer refuses. Version 1 retains the
legacy host behavior. Both the operator pin and Quipu's recorded trusted
signature are required; self-registration cannot widen local trust.

Before its single write, a job saves a private, fsynced prepared review record.
If the reply is lost, a retry reads back that same signed record; an unproved
effect is retained without automatic resend. The job queues only the record
reference, head and signer. The controller independently verifies that record
and scope before accepting an approval/change result, then performs ordinary
notification and UID teardown. A missing or unproved signature still becomes
blocked. No real signing identity or registration was created during source
qualification; per-job enrollment and native isolation remain rollout work.

## Scoped event recruiter source qualification

`st agent spawn --recruiter --ephemeral --job review --repo OWNER/REPO --pr N
--item ID --head SHA --dry-run` qualifies a request through a separate capability;
it does not make the principal an administrator. `--json` returns a
`shantytown.recruitment-plan/v1` object with `live: false`. This is not a spawn
receipt. Live requests currently refuse before the protected launcher because
its sudo transport is outside the recruiter's granted authority. A reviewed
controller handoff is a separate prerequisite; no fallback is provided.

The authenticated principal and UID come from protected identity configuration
and its existing introducer enrollment. A fixed protected `recruiters.json`
selects the permitted root, host, repositories and jobs. For example, an
operator policy can use principal `crew-recruiter`, UID 10001, an isolated
private home `/var/lib/shantytown/agents/crew-recruiter`, and the configured
crew host. Those values are not compiled into the authorizer. This source does
not create the user, enroll its key, install identity policy or enable a drain.
The recruiter's UID and a launched job's UID must be distinct. It receives no
administrator credential, sudo grant or controller socket.

The policy structure is `{"version":1,"principals":{"PRINCIPAL":{"uid":10001,
"root":"/absolute/crew/root","host":"configured-host","repos":["intigraph/widget"],
"jobs":["review"]}}}`. The file and its parent chain must be operator-owned and
non-writable by other users. Missing/malformed identity or scope, wrong UID,
root or host, extra command overrides, and all merge requests refuse.

Custody is only the native `chaski.github.work-request/v1` record read by the
existing helper from the exact item's description. Repository, PR number, job
and revision must match. PR prose, branches, trailers, comments and webhook
payloads establish no custody. The legacy record is deliberately reused;
introducing a stronger signed custody format is a separate schema change.

Qualification reads authoritative current PR state, bounded complete check and
status inventories, required contexts/app identities, and verified non-author
verdict state from the configured verdict graph. Unknown author/verdict state,
partial inventories, outside contributors, existing verdicts, changed custody
or a changed head refuse. The ordinary cap, protected job UID, hold and governor
checks remain in the source path. Merge recruitment remains disabled.

[Source demonstration](demos/scoped-recruiter/README.md) uses explicit fake
identity/forge adapters and no live job. Operational acceptance still requires
the separately authorized security migration, controller transport and a real
event-triggered review with durable receipt and latency measurement.

### Signed recruiter request qualification

`recruit_request.py` qualifies a bounded, domain-separated
`shantytown.recruitment-request/v1` envelope offline. Its fixed fields admit
only review launch or review stop; merge, arbitrary argv, environment, paths
and request-supplied keys are refused. Ed25519 verification uses the declared runtime dependency
`cryptography>=46,<47` and still refuses if it is unavailable. Source metadata
does not prove that an installed controller has the dependency or a key binding.

Authenticated requests expire within 120 seconds. A durable unique nonce is
reserved before exact native custody lookup, so a crash or custody refusal
cannot turn into an automatic replay. Refusals retain fixed reason labels,
without exception text or key material. The supplied `Binding` is an offline
fixture input, not proof of root-owned policy or introducer enrollment.

The read-only source loader checks the fixed root-owned controller key file
against the unique UID/principal in protected `identity.json`, with configured
host/root/repository validation. Installing that binding and proving introducer
enrollment remain activation work. Controller source qualification below integrates
fresh forge/check/verdict admission and stop-target ownership checks. Protected
persistent nonce state, live handoff and the separate activation/rollback approval
remain prerequisites before the first live signed request. Live recruiter
requests remain refused before native selection.

The proposed controller binding file is `/etc/shantytown/recruit-controller.json`,
with exactly `version`, `principal`, `uid`, `host`, `root`, `repos`, and
`public_key` (32-byte Ed25519 public key in lowercase hex). Neither this file
nor `identity.json` may have writable or symlinked parent components. Duplicate
JSON keys are refused. This is configuration read by the existing controller,
not a receiver service; no key file is installed by this PR.

The future live integration has one seam: the scoped-recruiter refusal before
`uid_launch` / `job_launch`. Only reviewed transport may replace that refusal
with `handoff(envelope) -> receipt`, retaining the receipt in `rec['recruiter']`.
It must not bypass the existing planner, admission or protected launcher gates.
For now the refusal remains. Root-pinned key reads reuse
`advise_signing._read(..., owner=0)` (also used by verdict signer pins), with
protected parent validation added; graph trust alone never supplies the key.

### Existing controller signed-request preview

`st agent spawn --recruitment-request --dry-run --json` reads one signed
envelope from stdin, ending at EOF (8 KiB and a five-second pipe deadline).
Only an independently authenticated controller administrator can use it.
Mixed CLI selectors, a recruiter acting as its own controller, a different
configured host/root, duplicate JSON keys and malformed or oversized frames
are refused. The request never selects the root-owned key or controller path.

`recruit_controller.receive` checks protected enrollment, request signatures,
expiry and nonce reservation before the existing fresh admission adapter.
Review launch rechecks the exact native item description, PR head, complete
checks and authoritative non-author verdict state. Review stop instead
requires the controller's own live job ledger to match the recruiter's exact
principal, host, item, repository, PR, head and distinct protected job UID.
Stop does not require green checks: a failed job must remain stoppable.
Custody and expiry are checked again after the reads; a slow read never extends
the signed lease. Refused or interrupted authenticated attempts remain spent
in the supplied ledger; durable fixture tests reopen it to verify refusal.

The CLI preview uses an **in-memory ledger**, so it writes no production state
and grants no durable replay protection or operational acceptance. Its receipt
always says `live: false`, `execution: refused`, `durable_acceptance: false`.
It contains a canonical request digest, not the signature or nonce. There is
no execution callback, listener, socket, service, enrollment or privileged
call. Without `--dry-run` the command refuses before reading stdin or keys.
The recruiter's existing live-refusal seam is unchanged. Live integration must
add reviewed protected persistent state and transport, then re-enter the normal
planner, holds, governor, cap and protected launcher gates; a preview receipt
is never a credential for skipping those checks. Merge verbs remain excluded.

### Protected nonce state and launch admission handoff

`recruit_store.Store` and `recruit_handoff.prepare` provide the next controller
library slice. Merge permitted; runtime activation gated separately. The CLI
preview still uses memory and the live-refusal seam remains in place. Neither
library is a new listener or a route to the privileged launcher.

The protected controller binding supplies the root. A provisioner must create
`<root>/ephemeral/recruitment` owned by the controller with mode `0700`; the
library never creates missing parents. The state file name is fixed. Directory
FD traversal refuses links, foreign owners and group/world-writable ancestors.
Files require controller ownership, mode `0600`, one link and a regular inode;
unknown entries, corrupt/incomplete databases and unexpected schemas refuse.
The qualified backend is Linux, using a pinned directory-FD path for SQLite and
its journal. Other platforms refuse this backend rather than using a weaker
path. Tests explicitly model trusted outer fixture ancestry; production has no
fixture exception.

SQLite uses DELETE journals and synchronous EXTRA, including directory sync
after journal removal. The database is bounded to 64 MiB, 50,000 nonces and
operations, and 200,000 audit rows. Capacity, corruption or an interrupted
initialization require operator disposition; records are never automatically
pruned, reset or replaced. Source rollback retains this state. Reservations,
operation claims, refusals and prepared observations survive process exit.
Fresh nonces cannot repeat a launch candidate for the same repo/PR/head/job.

The handoff first reuses signature, expiry and fresh exact-head authority
checks. Fields are detached from caller memory using the exact canonical bytes
covered by the signature before authority callbacks. It then durably claims the
candidate and enters the existing ephemeral lock, planner, cap, protected job
selector and governor interfaces. Quiet-time uncertainty and maintenance windows
refuse; malformed job inventory cannot appear as free capacity. Recruiter,
controller and review job identities must differ. Custody, expiry and the exact
unused protected capability are checked again after the gates. A refusal or
interruption spends the attempt; an unknown reply is not automatically replayed.

The resulting receipt reports a durable nonce and prepared plan digest, with
`live: false`, `execution: refused`, `activation: gated`. Preparation reserves no
runtime cap and proves no native UID drop. It creates no job/card/pane, invokes
no sudo or execution callback, and cannot be reused as a launch credential.
Runtime execution must re-enter the normal launcher and its current gates after
separate activation qualification. Stop still uses the earlier non-executable
preview; this handoff accepts review launch only. Merge verbs remain excluded.

### Controller durable preparation entry

`st agent spawn --recruitment-prepare --dry-run --json` accepts one signed
stdin frame using the existing bounded reader. This is an independent verified
controller operation, never a recruiter privilege. It enters the protected
persistent handoff library using the configured administrator, unattended
policy, native custody reader and existing governor adapter. Mixed request
selectors and an in-job identity refuse before stdin is read.

The explicit preparation mode **writes durable nonce/audit/operation state**;
`--dry-run` guarantees no launch, not a read-only database preview. Replaying
that signed frame, even after reopening the database, refuses. It never creates
state directories or enables a missing capability. Use the earlier
`--recruitment-request --dry-run` for the memory-only preview instead.

The resulting receipt remains `live: false`, `execution: refused`,
`activation: gated`. No transport listener or protected execution callback is
installed. Runtime activation remains gated on xu2; merge verbs are excluded.

## Watch evidence evaluator (source interface)

`shantytown.watch_program` validates immutable program data and evaluates
qualified samples without I/O, launch, signing, compensation or item closure.
It is not a long-running ephemeral agent or a second scheduler. Both future
selected-source adapters must call `WatchSpec.validate`; there is no TOML or
Quipu loader or fallback in this module.

The source schema contains version, run ID, selected-source SHA256, native
deployment receipt, frozen component identity, original start/window/cadence,
and named finite nonnegative upper limits. The sample grid always includes
the original end, even if cadence does not divide the window. Resuming uses
that same grid. Missing, duplicate, reordered, nonfinite or future samples
cannot pass, and a changed identity supersedes the run. An incomplete ended
window is UNKNOWN. A measured bound breach survives another missing metric.

The result separates safety, native activation and improvement. Configuration
true is not an activation input. An inactive capability can have a safe watch,
while improvement stays NOT_EVALUATED. An active capability needs positive,
finite, admitted comparable before/after cohorts; a flat result is explicitly
NO_IMPROVEMENT. Compensation always remains NOT_EXECUTED here.

A controller must authenticate the reader evidence and deployment/authority
receipts before calling this pure evaluator. Its strings and hashes do not
authenticate a caller. Managed-unit collection, durable evidence, callbacks,
signed non-review results and the shared Action executor remain separate
integration gates. This source interface does not satisfy live watch acceptance.


## Per-job usage on the ledger

When a job's result is first written (its report, or a forced teardown), st
records `usage` on the job record: the harness, each session id and model, and
token totals (input, cached input, cache write, output, reasoning, total). Codex
jobs are read from their durable `sessions` link
(`$XDG_STATE_HOME/shantytown/codex/<job>/sessions`, filtered to the job
workspace). Claude jobs are read from the job workspace's
`~/.claude/projects/<encoded workspace>` directory. A missing or usage-free
transcript records `state: "unknown"` with a reason, never zero. A capture error
never fails the ending. A later second ending keeps the first result and usage.

## Job-owned tool profiles and graph context

An optional `[ephemeral.jobs.<job>]` table narrows the MCP and workspace skill
kit for `review`, `merge`, `triage` or `task`. An absent table keeps the legacy
kit. An explicit empty table selects no MCP servers or workspace skills.
Unknown job names and fields refuse configuration; budget/model/trigger and
action fields are reserved for the JobSpec extension.

`verdicts` lists the verdicts the job may report (1-16 names, `blocked`
required; `failed` is recorded by st at teardown and refuses here). It replaces
the legacy enum `approve|request-changes|merged|blocked|done|failed` in the
job prompt and in `st agent spawn --report --verdict`, which refuses any other
name. `review` and `merge` may only narrow the legacy names, because their gates
key on `approve`, `request-changes` and `merged`. An absent key keeps the legacy
enum and the existing binding hash. Like any job table it also selects the tool
profile, so set `mcp_servers` and `skills` alongside it. The protected-UID rail
accepts the legacy enum only.

```toml
[ephemeral.jobs.triage]
verdicts = ["diagnosed", "needs-owner", "unknown", "blocked"]
```

```toml
[ephemeral.jobs.review]
mcp_servers = ["forge", "search", "structure", "quipu-read"]
skills = ["code-review"]
claude_ai_connectors = false

[ephemeral.jobs.review.mcp_tools]
quipu-read = ["quipu_query", "quipu_ask", "quipu_search"]
```

Server and skill names must exist in the deployment's tooling source. The
resolved table and its canonical SHA256 are recorded together as `jobspec` in
the job ledger. A changed or malformed binding refuses realization.
Provisioning removes unselected workspace skill links, preserves real files
and refuses unselected real skill directories. It does not edit shared role
settings. Codex uses a private job config with only selected MCP servers and
native `enabled_tools` filters. Claude uses a per-tool PreToolUse deny guard
for the bound subset (an allowed match never grants permission), job-owned settings, explicit
`--strict-mcp-config --mcp-config`, exact MCP permission allow rules and, by
default, `disableClaudeAiConnectors` plus `ENABLE_CLAUDEAI_MCP_SERVERS=false`.
An empty skills list also disables Claude slash commands. Existing sandbox,
permission and trust gates still apply; this is not OS isolation. A configured
profile on the separately staged protected-UID rail refuses until its projection
is qualified; the operator-owned staged kit is never silently rewritten.

A native Quipu read server can be declared without a bearer when the operator
has verified that anonymous reads work and writes require authentication. Only
an explicit `mcp_tools` subset of `quipu_query`, `quipu_ask`, `quipu_search` and
`quipu_graph_list` admits this anonymous profile. Direct Quipu writer tokens,
auth helpers, writer tools and stdio processes are refused for these profiles.
The ordinary crew's direct-Quipu credential guard stays in force. A mixed
operations server is not a substitute for this read endpoint. Declare its URL
in the deployment manifest; never put a credential into a job to make reads work.

The crew tooling manifest cannot carry a direct Quipu entry (crew provisioning
refuses one without a headersHelper), so a job-only server is declared in
deployment config instead and reaches only the job whose profile selects it:

```toml
[ephemeral.job_servers.quipu-read]
type = "http"
url = "http://quipu.example/mcp"
[ephemeral.job_servers.quipu-read.headers]
X-Quipu-Client = "st-job"

[ephemeral.jobs.triage]
mcp_servers = ["quipu-read"]
[ephemeral.jobs.triage.mcp_tools]
quipu-read = ["quipu_query", "quipu_ask", "quipu_search"]
```

A selected job server must qualify as the anonymous read-only profile above;
anything else refuses configuration. Its definition is copied into the bound
JobSpec (`server_defs`), so it is covered by the binding hash. It may not
shadow a crew server name. Crew cards never render it, and the crew guard is
unchanged.

At spawn, generic stored queries `references_to` and `entity_facts` collect one
bounded, one-hop snapshot: at most four exact IRIs, twelve facts each, a 64 KiB
response bound and a five-second request budget. The item IRI is derived from
the explicitly configured namespace; `--quipu-node IRI` adds an exact PR,
repository or service node without guessing identity from a label. The injected
block is capped at 6,000 JSON characters, with omissions and truncation visible.
A separate two-second exact-item read includes the newest three comment
snippets from the proven board graph; it does not promote them into all current
rulings. Missing configuration, failed/empty/capped reads and unproven named-graph
coverage remain UNKNOWN. The job still launches. This snapshot is evidence,
not authorization: historical notes cannot silently become current holds.
Triage follows the actual alert or failure subject and uses forge CI logs only
when the item identifies a CI failure.

Claude connector controls follow the [native settings reference](https://code.claude.com/docs/en/settings-reference#disableclaudeaiconnectors).

### Native enqueue process adapter

`python -m shantytown.review_enqueue_native --root ROOT --bindings DIRECTORY
--native /operator/protected/pr-risk.py` implements the Action process protocol.
All three paths come from controller configuration, never a review report.
The flag remains OFF by default. The fixed canonical service-admission policy
must already be adopted for this host and controller UID; absence refuses
instead of entering the native helper's legacy policy-absent behavior.
The native helper must be a root-owned regular file under root-owned,
non-writable, non-symlink ancestry. Inert source delivery is not adoption.

A trusted controller prepares two private single-link files in its private
bindings directory for each consumed intent: `<intent>.binding.json` contains
exactly `version: 1`, an absolute `checkout`, and the native classification's
`record` ID; `<intent>.record.json` contains the unchanged native classification.
They must be owned by the controller, inaccessible to job UIDs, and prepared
through the normal classification path. This adapter does not fetch a checkout,
classify, sign, create a native content review, generate bindings or install a
policy. Automatic trusted binding production remains a separate integration
step; missing bindings refuse. This version supports GitHub main/squash queue
admission through the existing diff-bound native path only. Unsupported native
admission requirements refuse; they are never relaxed.

The adapter matches the consumed private custody attempt and classification to
the candidate, reads the current PR node and head, then re-verifies the exact
GateApproval with both local operator signer pins and Quipu's recorded signature
verification. A revoked signer, CHANGES, unknown author, changed node/head or
mismatched record refuses. It then runs ONE unchanged native `enqueue` execute
with `--expect-record`; the native helper retains its record integrity, current
CI, review, operator hold and shared service-order checks. Native review
exemption does not waive the separately required signed job approval. A
GateApproval is never converted into a native content-review receipt.

Only an exact `ENQUEUE VERIFIED` record/head/entry response becomes `queued`.
A timeout, process failure or mismatched reply is UNKNOWN, even if it resembles
a refusal: a remote write may already have happened. The outer report custody
retains that result without retry. No merge command or merge job is invoked.
This source contract and offline process fixtures are not real queue acceptance.

### Automatic trusted binding production

An operator can instead select `python -m shantytown.review_enqueue_bindings`
with the same `--root`, `--bindings` and `--native` arguments. This is another
explicit process choice under the existing default-OFF flag; the prepared-record
adapter above remains available. No deployment configuration is changed here.

The private bindings directory must contain `repositories.json`, owned by the
controller with no group/other access, with exactly this data shape:

```json
{"version": 1, "repositories": {"example/project": {"checkout": "/operator/checkout"}}}
```

At most 64 repositories qualify. A missing, unreadable, malformed, unlisted or
relative checkout entry refuses before any classification. The controller
provides a fetched checkout containing the exact objects; this process never
fetches or runs a Git remote helper. A review cannot choose a path or author.

For a consumed intent, the producer exclusively creates and fsyncs
`<intent>.prepare.json` before any classification. The current pinned signed
APPROVE and exact forge PR node/head supply identity and author. ONE normal
native `classify` creates the private record with umask 077; its author, head,
repository, number and main/squash/non-one-way scope must still match. The
producer then writes and fsyncs the binding and uses the native adapter, which
re-reads configuration, current PR and signed approval before enqueue. No
content-review receipt is manufactured and no model merge job runs.

A parallel call, crash, partial output, existing binding or consumed preparation
claim refuses. Nothing resets or deletes the claim, overwrites old evidence or
retries either classification or enqueue. Reconciliation is an operator action.
Classification can consume the existing native scoring budget: the process is
not a free read, and activation must measure its whole graph/forge/cost envelope.
Its subprocess requests share a 100-second deadline (classification at most 45
seconds), leaving margin before the outer 120-second Action timeout. Graph
verification also consumes that elapsed allowance; no queue command starts
after it is exhausted. These source controls do not establish a deployed
end-to-end budget or real approve-to-merge acceptance.

### Retired job settings

After authoritative teardown, the emitted per-agent configuration is renamed
with a `.retired` suffix. Session history, rules, credentials and other files
remain in the job home. The ordinary reap pass also repairs settings left by
older completed jobs; its dry run reports the proposed retirement. It uses the
job ledger, preserves live jobs and unknown settings, and refuses symlinked
paths, surviving crew cards and existing retirement archives. This prevents
ended jobs from appearing as unknown-role hook drift without hiding live hook
failures.

### Operator-pinned native source custody

The native adapter accepts only `/etc/shantytown/native-enqueue-source.json`,
installed through the reviewed operator delivery lane. It names the normal
ownership-neutral checkout, its owner UID, exact Git revision, entrypoint and a
full-code-closure SHA-256. It does not relocate or copy the native helper and
never falls back to an unpinned path. The pin and lock metadata remain root-owned;
source files may belong to the explicitly pinned operator UID. Unknown owners,
group/other-writable code or metadata, changed revision and closure mismatch
refuse before native execution.

```json
{"version":1,"root":"/operator/neutral-source","entrypoint":"scripts/pr-risk.py","owner":1000,"revision":"0000000000000000000000000000000000000000","closure_sha256":"0000000000000000000000000000000000000000000000000000000000000000","lock_file":"/etc/shantytown/native-source-custody/source.lock"}
```

This is a schema example, not an admissible deployed pin. Measure a frozen
checkout with `python -m shantytown.native_source_pin measure --root PATH
--owner UID`, then recompute and read back the digest after the reviewed
Gold/refresh delivery. The closure covers every versioned file, file ownership,
mode and content, internal file-link targets and local Git configuration. Missing
or non-versioned files, hardlinks, external links, configuration includes and
exhausted bounds refuse. The limit is 10,000 closure files and 1 GiB, including
Git configuration; an exhausted measurement is UNKNOWN, never a partial pin.
The interpreter, external executables, credentials and target repository
profiles still require their existing runtime qualification.

Only conventional tagged bytecode cache files are excluded. Native subprocesses
use `-I -S -B -X pycache_prefix=/dev/null`: no user/site initialization, no cache
writes and no cached local modules. A legacy or source file hidden in an excluded
cache directory refuses. A real poisoned-cache control demonstrates that these
flags load the pinned source instead.

Consumers take the fixed root-protected lock shared, verify the complete source
and pin, and retain the lease through execution. The native child inherits the
lease FD, so killing its adapter parent does not release source custody early.
The normal refresh lane must use `native_source_pin refresh -- ABSOLUTE_COMMAND`
for its exclusive lease before chmod/fetch/merge or pin replacement. The existing
refresher's guarded handoff checks the exact inherited lock inode, source root,
caller and exclusive lock; an environment FD number alone grants nothing.
An active reader defers a refresh tick. When both operator policies are absent,
the old refresh lane is preserved; an absent canonical pin always refuses a
native consumer, and a malformed present canonical pin refuses without fallback.

Rollout must install both sides before adopting the canonical pin. Provision the
lock with access only for the pinned source owner, protected controller and
operator; job UIDs must fail the read/lock control. Keep the two accounts separate
without granting new groups or sudo. Normalize only reviewed mutable Git metadata
permissions, measure afterward, and retain a mutated-file refusal control. Move
pins only under the same exclusive lease, through the reviewed Gold/refresh
lane with digest readback. No pin, ACL, owner, mode, source refresh, canonical
admission or runtime flag is changed by this source slice.

The reviewed refresh finalization calls `normalize-refresh-metadata --fd FD --root PATH`
under its inherited exclusive lease, before publishing a successful refresh mark.
Only `.git` 0775/0755 -> 0755 and its single-link regular `config`
0664/0644 -> 0644 are admitted; both exact pinned owners/modes qualify before
either change. Unknown metadata refuses. It then measures the complete closure
and prints a proposal; it never writes the operator pin. A mode change therefore
continues to refuse native execution until the reviewed pin move/readback. The
first pin/lock provisioning and canonical adoption are separate admitted steps.

For first provisioning, the fixed root-protected
`/etc/shantytown/recruitment-staged/native-enqueue-source.candidate.json` may
supply the writer policy while the canonical pin is absent. Only the refresher
consults it; consumers never do. A malformed present canonical pin refuses rather
than falling back. The root-staged candidate grants only the same exclusive
writer lease and must name the existing fixed lock, exact source owner/root,
revision, entrypoint and full closure digest. It starts no controller or job.

`measure-normalized-metadata-proposal --root PATH --owner UID` reads the complete
closure without changing modes or pin bytes. Its tagged proposal hashes the
future 0644 Git config metadata while admitting only the two declared current
mode pairs; every other custody/closure check stays strict. After reviewed root
staging and lock provisioning, the normal refresh verifies the same exclusive
lease, performs the two exact normalizations and measures the actual closure.
With only a staged candidate, that actual revision/digest must match the proposal
or refresh refuses before its success heartbeat. Canonical adoption still needs
the reviewed pin move and readback; absence continues refusing consumers even
when writer normalization succeeds. No placeholder pin is needed or admitted.

Recognized cache metadata also includes released numeric pytest tags such as
`module.cpython-314-pytest-9.1.1.pyc`. These remain regular, single-link files
under the excluded cache directory with known owners. Native isolated Python
bypasses their bytecode through its separate cache prefix; the poisoned-bytecode
control includes both ordinary and pytest-tagged poison. Arbitrary source,
untagged bytecode, unknown tag text and redirects still refuse.

## Codex jobs refuse interactive approval

A controller-ledger-bound live or launching Codex job uses
`approval_policy="never"` in both the local TUI and managed remote daemon.
Unlisted commands that require approval refuse immediately; the job must report
the original refusal or blocked evidence through its existing report command.
No sandbox is widened and no extra command is allowed. Ordinary crew cards keep
their operator-selected approval policy. This prevents an unattended job from
waiting on a human picker after a sandbox-limited read fails. The policy does
not make that read succeed or authorize a retry outside the sandbox.
