# shantytown — the CLI

> Stiwi, 2026-07-16: *"there needs to be a cli and a primer"*.
>
> Gas Town ships ~110 commands and we measurably use a dozen. This is not a smaller version of that
> list. It is **the short set**, and the discipline is that each command earns its slot — the count is
> now pinned by a test (`tests/test_command_count.py`), so a new command either updates the docstring
> and this doc, or fails CI.

## Where each command is described

This page lists every command, the output flags and the exit codes. Each
group of commands has its own page:

| page | covers |
|---|---|
| [Starting a session](cli-session.md) | `st prime`, `st anchor` and `st attach`: what an agent reads when a session starts, and what a launch must prove. |
| [Dispatch and intake](cli-dispatch.md) | `st go`, `st sling` and `st task`: how work reaches an agent, how intake is ranked and what stops a dispatch. |
| [Work items, gates and cost](cli-work-items.md) | The commands under `st work` that change an item, hold it behind a gate or account for what it cost. |
| [Creating and running a crew](cli-crew.md) | `st fleet init`, `st fleet start` and the commands that choose each agent's program, account and host. |
| [Pane states and stops](cli-stops.md) | How `st` reads a pane, what each state means and how a stop is decided and recorded. |
| [Messages, memory and history](cli-messages.md) | `st inbox`, `st work directive` and `st agent memory`: what is delivered, what is kept and what is archived. |
| [Supervision, holds and budgets](cli-supervision.md) | `st fleet watch`, `st fleet tend` and `st fleet hold`: what supervision reports, what holds launches and how accounts are paced. |
| [Health and tooling](cli-ops.md) | `st ops doctor` and `st ops provision`: what is installed, what is stale and which credentials a session needs. |
| [Pushes and pull requests](cli-repo.md) | `st repo push` and `st repo pr`: where a push may go, what a pull request is checked against and how merged work is recognized. |

## The whole surface

```
st prime [agent] [--brief|--section NAME] [--static] [--json]
                              tool primer plus bounded, read-only crew and anchor summary
st anchor [--short|--events|--harness]
                              who am I, what's on my plate         <- the anchor
st go <item> <agent>          dispatch. this is the one that matters. the agent is required.
st sling <bead>                  hand a beaded design to the executive for scheduling.
st inbox <agent> <message>    put a message in an agent's inbox (send-keys; -d persists)
st inbox [--count|--read|--read-id ID]
                              read or acknowledge your own inbox
st task <title>               create a work item
st crew [--count] [--wide]    who exists, state, role, assigned title, WHO IS FREE
st attach [agent]             attach to a crew member — STARTING them if down (pane+socket resolved)
st attach --no-start          attach only if already running; never create a session
st work                       the item and the board
  item <show|update|comment|close> <id>
                              exact-ID operations on the configured work tracker
  repool <item>               hand an item back to the pool: status -> open AND
                              assignee cleared, one verified write. Clearing the
                              assignee alone leaves it in_progress — off `bd ready`,
                              every haul, and every plate at once.
  defer <item> <kind> --reason-file <path|->
                              park work with exactly one structured blocker kind
                              (`bead|human|access|external|parked`) and a durable
                              reason naming its referent/re-test condition
  hold-feed <agent> --until <UTC|closed:id> --reason-file <path>
                              hold automatic feeds only; --status/--clear inspect/release
  cost [bead] [--sync]        parser-owned cost reads and closed-bead/metric publication
  triage [item ...]             preview Jev board suggestions; --publish comments only
  dream [--run]               inspect or run one bounded spare-capacity reflection cycle
  jobs [new|list|check|run|history]
                              jobs declared in Quipu ([jobs] graph); `new` writes one
                              (--weekly DAY HH:MM | --every), Chaski fires it. Cron and
                              interval job files are refused; other <root>/jobs/*.toml
                              files are deprecated; see docs/jobs.md
  directive [list|mark|dismiss|track|flush]
                              operator messages st captured verbatim; mark/track confirm a Directive
st agent                      one agent
  new <agent>                 create an agent from a card
  spawn --pool <status|size N|config|pause|drain|resume>
                              see and manage the ephemeral pool: runtime size, pause (spawns queue),
                              drain (spawns refused, live jobs finish), resume. docs/ephemeral-agents.md
  spawn --ephemeral --job <review|merge|triage|task> --item <id> [--harness] [--repo R --pr N]
                              an EPHEMERAL agent for one job, managed by the administrator or a lead:
                              own worktree, deadline + turn/context budget, counted in the cap
                              and the governor, reports its verdict to the administrator and the
                              item, then is torn down. Over cap it QUEUES a ticket (--priority N)
                              that the job end paths drain, routed by harness cap and --track
                              share. A task job REFUSES without --repo OWNER/NAME (also when
                              only --checkout is given): it would get no source worktree, and
                              nothing is queued or launched. --list · --stop NAME|TICKET · --retry NAME
                              · --report (by the agent) · --reap (tend) · --drain
                              · --drain-events FILE (chaski pr-lifecycle events, idempotent).
                              docs/ephemeral-agents.md
  stop <agent> [--reason]     stop it, and RECORD that it was deliberate
  harness <agent> [claude|codex]
                              convert one agent to another harness: writes the card (with a
                              .bak), refuses a role the deployment pins, and relaunches with
                              `--now`. Omit the target to report what the card runs
  account <agent> [name]          select account, harness and default model; --now queues a safe cycle
  cycle <agent> [--self]      clear an agent's context WITHOUT destroying its runtime:
                              checkpoint -> stop -> relaunch -> re-dispatch. `/clear`
                              drops bypass into MANUAL; this keeps it. --self REQUESTS
                              your own cycle (an agent cannot stop itself), honoured
                              by `st fleet tend`. --allow-loss to cycle over unsaved work.
  advise <agent>              keep or cycle at a handoff: depth, measured cache TTL and
                              idle time, and any posted relatedness signal. --related P
                              / --decision keep|cycle --by WHO posts one. --json.
  input <agent>               what's in their input box: EMPTY | TYPED | GHOST, with the
                              capture evidence. --clear (typed only) --dismiss. NEVER submits.
                              Codex multiline clear verifies the empty placeholder;
                              BUSY refuses editing, and no repaint stays UNKNOWN.
  ask <agent>                 the QUESTION they're blocked on: prompt, the command being
                              approved, and the numbered options VERBATIM. read-only.
  answer <agent> <N>          select option N. refuses on a pane that isn't on a picker,
                              echoes what it selected, and records who answered.
  log [agent]                 what happened
  memory <agent> <capabilities|inspect|read|query|export|commit|deliver|stage|sync>
                              explicit versioned memory transport; no native root replacement
  history <agent>             captured transcripts, and whether the source survives
  remote {list|pair <agent>}  discover existing Codex servers or request a manual pairing code
  stats [agent] [--files]     files/skills plus provider tokens and cache dimensions
  stats --graph               graph-context adoption: what share of dispatches carried a
                              quipu node, what share stated a reason for having none, and
                              which agents have never cited one. A read over a ledger, so
                              it is a flag here rather than a verb of its own.
st fleet                      the whole crew
  start [--mode lite|heavy]   BOOT the town by mode: the admin alone, or every card. idempotent
  start <agent>...            bring up exactly these agents (already-up is a SUCCESS, not a refusal)
  tend                        supervise the crew: respawn what DIED, never what was RETIRED
  tend --reauth               relaunch every AUTH-DEAD agent (run AFTER the operator re-logs in)
  tend --target N             respawn only toward N LIVE agents (scale UP on loss; never stops a surplus)
  roles [--check|set|band|sync]
                              the hierarchy: show it, verify it, write it, import it.
                              `band <agent> <first|normal|support|last>` writes the
                              SURVIVAL band — which agents a usage throttle spares.
  init                        scaffold a NEW deployment (wizard): store, cards, hooks, config
  hold gaming [--clear|--status]
                              hold local launches during a gaming session
  window plan|drain|clear|release|abort <id>
                              transactional fleet-maintenance ledger + relaunch lease
  dashboard [admin]           live, tier-scoped view: roster/state/work, self-refreshing
  watch [--peer|--metrics]    one liveness pass on the PEER host's administrator
st repo                       a shared project repo
  worktree <repo> [agent]     provision an agent's isolated worktree off a SHARED project repo
  push <repo> [agent] --branch <destination>  push wt/<agent> to EVERY remote; requires explicit destination
  context <query>             what code should I be looking at? (bobbin)
  pr <owner/repo> --bead <id>  complete overlap inventory; --create records decisions then creates
st ops                        the installation
  doctor [--install]          what's installed, stale, missing (out-of-box)
  provision [agent]           register Quipu tooling for local crew without launching
    --instruction-report     compare composed graph instructions and tooling bytes without provisioning
  subscribe                   watch quipu entity events; route governed workflows to the admin
  hooks <register|list|check> keep tools' registered hook bundles rendered, and check they are
  help <topic>                rationale pages: handoff/cycle, haul, inbox
st <launch cmd> --despite-hold  launch THROUGH a gaming hold, for that one command
```

Cycling leaves the existing clone and worktrees on disk. Clean unpublished
commits are reported without blocking when the push authority guard refuses
publication, just as during a measured remote outage. The authority check is
shared with `st repo push`; cycling never grants push permission. Preserve the
branch and arrange publication to an authorized peer. Uncommitted work still
blocks, and the durable checkpoint requirement still applies.

For tracked files deliberately modified by each installation, commit a
`.st-per-install` file at the repository root containing one exact relative path
per line (blank lines and `#` comments are allowed). For example:

```text
# Generated host wiring; do not publish the local modification.
scripts/hooks/pre-commit
```

Only unstaged modifications to existing regular files named by the committed
manifest are exempt from the cycle loss gate. The verdict names them as
`per-install, not loss`. Staged changes, deletions, renames, symlinks, and edits
to undeclared paths still block. Invalid entries (absolute paths, traversal,
globs, or the manifest itself) disable the exemption. Local edits to the manifest
do not change the policy. No file or index flag is changed; refresh/staleness
checks continue to see these modifications.

Context occupancy hints are opt-in in `shantytown.toml`:

```toml
[session_budget]
context_window = 1000000
context_threshold_pct = 50
context_hard_pct = 70
context_nudge_pct = 35
context_nudge_repeat_seconds = 120

# Administrator incident policy: first reminder at 250k of the declared 1M,
# then at 350k, 450k, etc. Workers retain the global cadence.
[session_budget.context_by_role.administrator]
context_nudge_pct = 25
context_nudge_step_pct = 10

[session_budget.context_by_role.lead]
context_threshold_pct = 60

[session_budget.context_by_agent.alice]
context_window = 200000
```

Declare the actual deployment window; transcript model names can omit window
variants. Role and agent overrides inherit global settings; an agent override takes
precedence over its role. Use agent declarations for mixed-model crews. Without an explicit window, Codex uses the server-provided `model_context_window`
from the same usage record. Claude needs a declaration; missing capacity reports
UNKNOWN. Enabling any context setting enables coverage for the whole crew:
otherwise undeclared agents use a 50% threshold with no assumed capacity. A
role/agent-specific capacity is never borrowed by another agent. Omitting all
context settings leaves hints disabled.

The existing PostToolUse capture hook reads the latest turn's input occupancy,
including Claude cache tokens, and adds nonblocking preparation reminders during
long turns for every role, including administrators. `context_nudge_pct` defaults
to 15 percentage points below the hint (or half the hint for thresholds below 30%).
Reminders repeat every `context_nudge_repeat_seconds` (default 120, range 1–3600),
or after another five percentage points. Explicit nudge percentages must be below
the hint. Optional `context_nudge_step_pct` (finite, greater than zero and below
100) replaces timed preparation repeats with milestones anchored at the nudge:
25 with step 10 means 25%, 35%, 45%, and onward. A late first observation at 26%
still repeats at 35%. Elapsed time alone does not repeat this preparation advice.
Stop's soft/hard decisions and bounded exceptions retain their existing cadence.
Omit the step to retain the existing worker behavior. This setting inherits
through role and agent overrides like the other context settings.
Session changes, compaction below the nudge and threshold crossings re-arm
feedback; busy observations do not postpone the next reminder. Unknown or invalid
capacity never becomes a percentage.

Stop also emits early preparation advice and repeats ordinary handoff hints at
the configured interval. Tool reminders never call Jev, suppress Stop decisions,
extend a bounded exception or schedule a cycle. Jev exceptions still expire after
ten minutes or five percentage points; the hard limit still has no override.
Tool feedback scans at most the latest 2 MiB of transcript, never a partial first
record. Usage outside that bound stays UNKNOWN until a fresh record arrives.
Live acceptance requires both the installed capture hook and a fresh usage event;
source tests alone do not prove delivery to a running administrator.
The [compact checkpoint template](guides/context-cycle.md) gives one request command;
`--checkpoint-file` posts the handoff, so a separate comment is unnecessary.
Explicit checkpoint and graph pointers avoid repeated discovery/refusals.
The resume hook emits the saved brief in the `SessionStart` JSON
`hookSpecificOutput.additionalContext` field, like the anchor hook, and consumes
it once. With no pending brief it emits nothing.
They name `st agent cycle --self --checkpoint-file <notes-file>`; they never schedule
that cycle or latch a work ceiling. Finish critical work before checkpointing.

Before ending the turn for a cycle, stop or await only your own running background
tasks. Claude agents use `TaskStop` for their running tasks; Codex agents inspect
with `/ps`, then stop or await their running processes. A remaining background
shell prevents the cycle from reaching its idle boundary. The self-cycle waiter
logs the observed shell count when it changes and still waits safely; it never
stops those tasks itself. After the tasks exit, the next idle poll can serve the
existing request. While a fresh, unrefused self-cycle request is pending,
Stop advice and self-feed stay silent so the pane can reach idle. Refused or
stale requests resume normal advice; automatic requests do not silence it.
This does not relax the waiter's busy-pane or background-task checks.
The detached waiter uses an interpreter verified by the installed-hook resolver
and starts from `/`, so a repository directory named `shantytown` in the caller's
working directory cannot shadow the installed package. If no usable interpreter
is available, the request remains pending for tend and the spawn reports why.

**How a cycle is performed, and what it costs you.** `st agent cycle` chooses the
least destructive mechanism the agent's state allows, and only the last resort
takes the tmux session down:

| mechanism | what happens | who notices |
|---|---|---|
| in-place clear | the harness's own clear command is typed into the live pane. The process, the session, the MCP kit, the skills and the permission mode are never torn down. | nobody — an attached operator stays attached and keeps watching |
| respawn | the process is replaced; the session, and every client attached to it, survive. | the pane restarts in front of you |
| relaunch | the session is destroyed and a new one started. | **every attached client is detached** |

The in-place clear is the default and needs four things: a harness that declares
a clear command (Claude Code does; codex does not), an agent that is idle, an
empty input box, and — for a card that runs on bypass — a harness that can prove
from the pane that bypass survived. A clear is typed at the same prompt a human
uses, so into a busy pane it queues behind the turn and into a pane with
unsubmitted text it appends to it; neither is a clear, and both are worse than
the slower path. Anything missing drops to respawn, which is still seamless for
an attached operator. `--no-in-place` forces a respawn when you want the process
restarted as well as emptied — a wedged runtime, a settings file it must re-read,
a new model on its card.

Before a restart, cycle checks admission under the same account lock used by
launches. A replacement reuses its own live local slot; at the cap that permits
a replacement, but an already over-cap fleet still refuses it. A refused launch
leaves the existing session running and does not record a deliberate stop.
The full stop/start fallback checks launch gates before stopping, while holding
the lock through the replacement.

Cycle's publication check counts only commits reachable from that worktree's
HEAD, so another agent's unpublished branch in the shared repository does not
block it. It prune-fetches the current branch's tracked remote and any peers
explicitly marked `remote.<name>.st-push-allowed=true`, never a declared mirror
(`st-push-role=mirror`). Main's upstream is a
fallback only when neither is configured. Only successfully refreshed peers can
prove publication; deleted branches and stale refs on skipped or failed remotes
cannot. Tracking a fork does not require publishing to the original repository.

**What the emptied session is handed.** A cycle writes a resume brief before it
touches anything, and a SessionStart hook injects it into the fresh context. It
carries the checkpoint, the checkpoint bead, the graph nodes named on the request
and the work item that was re-dispatched — as POINTERS, not contents, so the new
session opens small and knows where to look rather than opening large. It is
delivered exactly once: a brief that survived its own delivery would be re-read
at every later session start, telling an agent to resume work it finished two
sessions ago.

Before accepting a self-cycle, optional Jev advice checks the checkpoint's exact
next step, landed versus local work, and decisions made. Configure
`SHANTY_CHECKPOINT_JEV_COMMAND` as the installed Jev MCP server command in `[env]`;
it falls back to `SHANTY_CREATE_JEV_COMMAND`. The judge sees only checkpoint text,
at most 8192 characters, with a five-second total transport deadline. Its yes
probability must reach 0.75; a lower result triggers bounded missing-piece checks.
These are inferred judgments, not proof that a handoff is correct.

A thin handoff gets one rewrite opportunity per launch when the pane reports
context below the cycle line. Re-running the cycle then proceeds even if the
handoff is still thin. At or past the cycle line, with unknown depth or launch
identity, or when Jev or its telemetry is unavailable, advice never refuses the
cycle. `--allow-loss` also skips the rewrite delay. Existing durable-checkpoint
and work-preservation gates still apply. Automatic servicing does not rejudge
an accepted request; dry runs make no judge calls or quality-ledger writes.

Verdicts are recorded privately in `<root>/checkpoint-quality.jsonl`, including
question/input provenance, probabilities, model, usage, latency, and whether a
rewrite was offered. This ledger is available to decision evaluation tooling;
it does not promote inferred judgments into the knowledge graph.

`st anchor` shows context measurement at startup, and `st crew` shows occupancy
from that session's most recent hook transcript plus a named summary of live
agents with unmeasured context. An agent without a current Stop observation is
unmeasured, even if its window is configured.
Missing, stale or unreadable observations say UNKNOWN. Consumption exceeding
the declared window reports a configuration fault, never a clamped percentage.
A too-large window cannot be detected from usage alone; verify the configured
window against the launcher when enabling this policy.

Assigned titles are shown with `…` when the default `st crew` output clips them
at the terminal width. `st crew --wide` (also `--no-truncate`) prints the complete
title, suitable for piping or terminal scrollback. Control characters in titles
are rendered as spaces so tracker text cannot move the terminal cursor. The
bead-backed roster shares one store/readiness snapshot across its assigned rows;
a new invocation reads fresh work. Seeds roster membership and status validation
share one candidate observation, and capacity reuses the same render. Missing,
unknown-only or nonplain-only statuses keep assignments and capacity UNKNOWN;
a failed read never means an empty roster.

Seeds owner projections can retain a bounded successful candidate observation
across unrelated transactions. The scoped change feed must certify its original
watermark before a result is returned. Selected field changes reload those fields;
membership changes restart selection. Missing, partial or changed-store evidence
remains UNKNOWN. No stale answer is returned when the proof fails. Ordinary
query caching and the `ST_SEEDS_READ_CACHE=0` rollback remain unchanged.

In an interactive `st fleet dashboard`, **Left/Right** scroll assigned work eight
characters at a time; **Home/End** show its beginning/end. `‹` marks hidden text
to the left and `…` hidden text to the right. Shorter rows clamp independently,
so End reveals each row's suffix. Agent/state metadata stays fixed; narrower
panes reserve space for the work instead of retaining every metadata column.
**q** or **Ctrl-C** exits and restores the terminal. The current snapshot is
reused while scrolling; only the refresh interval queries the tracker again.
`--once` and redirected output remain plain text without keyboard handling.

The `st crew` tree column uses cached remote refs by default. `+N` counts
commits absent from those locally known refs; it does not prove nobody else
has them. Old or unknown-age refs, a failed fetch, or an unreachable remote
produce `?` and qualify cached ahead counts as possibly already pushed.
When one tree has measured differences and another cannot be verified, the
combined cell keeps the uncertainty, for example `-2/+1?`. `st crew --trees`
opts into fetching and pruning discovered worktrees; an unreachable remote
is reported without waiting for a doomed fetch. Refresh your own refs before
acting on an apparent unpushed count. These display qualifications do not
change the raw counts used by the cycle work-protection checks.

`st go` and `st agent cycle` take `--quipu-node NAME` (repeatable) or
`--no-graph-context REASON`, and every dispatch writes one row to
`<root>/logs/graph-adoption.jsonl`. `SHANTY_GRAPH_CONTEXT=require` turns the
default warning into a refusal; a node the graph positively does not hold is
refused under either setting, while a graph that cannot be reached never
refuses — absence and silence are different answers, and only one of them is
the dispatcher's problem.

`st agent stats` keeps its row extensible through `key=value` fields. When at least
one local transcript has a usage snapshot, the row includes
`usage_known=1 usage_in=N usage_out=N cache_read=N`. `usage_in` is normalized
prompt traffic: Claude's base, cache-read and cache-creation fields are summed;
Codex input already includes its cached subset. This makes
`cache_read / usage_in` a provider-independent prompt-cache hit rate. The fields
are omitted—not zeroed—when every matching transcript is unknown.

Forty-nine. Eight verbs at the top level and forty-one grouped commands under five groups
(`work`, `agent`, `fleet`, `repo`, `ops`). A group is a namespace and runs nothing, so it earns no
slot; the count is the leaves. The flat spellings from before the grouping (st cycle for
st agent cycle, and so on) still parse into the same handler, print one line on stderr saying
where the command went, and go away in two releases; `ST_QUIET_ALIASES=1` silences the line.
`--dry-run` is on every command that writes, from commit one. The surface grew past the
original eight, each slot on a specific ask — not drift: **inbox**/**task** (the dispatch/tracker
pair, owner-directed), **context** (the bobbin Context protocol), **doctor**
(out-of-box detect/install, Stiwi's direct ask), **subscribe** (the quipu events adapter,
routing governed workflows to the admin), **repool** (the whole hand-back in one verified
write — clearing an assignee alone leaves an item in_progress, which parks it outside `bd ready`,
every haul, and every plate; a hand-back that drops work off the board was the measured defect),
**hooks** (registered hook bundles: a tool declares its hooks once and st renders them into every role's claude and codex settings on every emit, so a regeneration can no longer silently drop them, and `check` reports drift — Stiwi's 2026-09-29 ask, aegis-68j0ys), **defer** (the whole structured park: status, exactly one blocker-kind label, and a durable
reason in one verified action), and **history** (the durable transcript archive: codex writes its
rollouts under a CODEX_HOME on tmpfs, so an agent's sessions — reasoning included — were RAM-resident
and died with the machine; `history` lists what was captured and, per session, whether its source
still exists, because a row whose source is gone is recoverable only from the archive). Each is
named on purpose: this doc once
said "eight" while the code had twelve, and a count nobody enforces is a comment — in the one repo
whose whole pitch is the exact count, that was the bug.

For a bundle's Codex `notify`, each emitted file records an ownership fingerprint
in a comment. Unregistering the bundle removes its unchanged notify value on
regeneration. An operator's replacement and older unmarked values survive:
matching a command alone is not proof that st owns it. Workspace and project
trust rewrites preserve the fingerprint while the notify remains unchanged.

The twenty-sixth is **dream**: the inspect/preview/manual-run surface for bounded
background reflection. Cycles require explicit admission; `tend` never creates
them because an interval elapsed. Status shows the last cycle, rotation and
capacity policy without running supervision.

The twenty-seventh is **defer**: the tracker already knew how to hide work, but bare
deferral did not require the deferrer to state whether the blocker was a bead, human,
access capability, external event, or no blocker at all. `st work defer` records that kind
and requires a testable resume condition: `--until YYYY-MM-DD` (day) or
`--until YYYY-MM-DDTHH:MM:SSZ` (exact UTC time), an existing
`defer_until`, or a `resume_when: closed:<id>` / `date:<ISO date>` / `release:` / `installed:` marker. Re-deferring records exactly one active marker; a new condition replaces older markers, retaining their values and prose as inert history. A new `--until` replaces a copied date marker, and a new date marker updates an existing deadline. Without a new condition, the existing gate remains; ambiguous old markers require an explicit condition. It
writes and verifies the reason and condition before changing status, then verifies
status, blocker kind, reason and condition together. An interrupted write returns
non-success with read-back evidence and no automatic retry. An already-deferred
item is only a no-op when all requested fields are present.

CI, review and merge waits stay `in_progress`, including P0 and milestone work.
Record the exact head/run/review wake on the item. `st work defer` refuses both
`ci-terminal:`/`pr-merged:` conditions and explicit CI/review/merge waits before
any write, even with a 24-hour backstop, `--window` or `--dry-run`. Historical
CI/PR deferrals remain readable; this does not manufacture green CI or release
any existing gate. Record real technical prerequisites as dependency edges;
external non-CI gates name their event with `blocked:external`.

Other admitted asynchronous waits still require a testable condition and the
existing backstop. A real scheduled appointment may use `--window --until <UTC time>`; this never bypasses CI, human decisions, dependency checks or resume gates.
Capacity holds do not authorize a date defer or repooling; retain the hold and
ask the lead for ready work.

A `closed:` deferral with a marker-only reason can resume automatically when
the named item closes. The required one-line `--dependency-reason` and the
command's exact scope flag are informational metadata; they do not turn that
reason into a prose gate. Any additional prose, historical notes, unknown
fields or extra resume markers still require judgement. Human, access
and parked labels, future deadlines and other open dependencies
continue to hold the item. The scheduled sweep reads the complete item and its
condition again before reopening it.

A `blocked:external` hold can be satisfied by an unambiguous `closed:`,
`release:` or `installed:` condition only when its evaluator returns a definite
MET. An unmet condition, an UNKNOWN read, additional prose or a human/access
hold keeps the item deferred. A `date:` review never grants that permission.

The sweep keeps a complete observation of all selected deferrals. If Quipu
rejects a field batch with its explicit structural-cost HTTP 400 and asks for
smaller requests, the reader halves that batch and retries each half within the
original batch's time budget. It keeps both graphs and every evaluation field.
A single candidate that still exceeds the limit is UNKNOWN; no candidate is
skipped and no partial observation permits a release. Other HTTP failures are
not retried by this split path. The server's structural limit stays unchanged.

Ordinary pacing goes to a live owner, with a live lead as fallback when the
owner is unexpectedly down. A valid deliberate-stop record changes that route:
the administrator receives one digest per stopped owner, never per-item wakes
in the lead's pane. Each digest counts all priorities and lists P0 items; an
explicit display cap points to the complete local inventory at
`notify/deferral-stopped-owners.json`. Read-error and authority findings remain
visible in that owner's digest. Unchanged findings stay suppressed, failed
delivery or inventory publication remains retryable, and clearing the stop
restores the owner route. A malformed stop record is UNKNOWN intent, not proof
of a deliberate scale-down. Notification routing never releases a gate,
reassigns an item or resumes a stopped runtime.

Historical forge deferrals retain two registered generic readers. New CI/merge
waits stay in progress; `st work defer` refuses these kinds:

- `resume_when: pr-merged:<github|forgejo>/<owner>/<repo>#<number>` wakes on an
  observed merge of that exact PR. Closing an unmerged PR does not satisfy it.
- `resume_when: ci-terminal:<github|forgejo>/<owner>/<repo>@<full-sha>` wakes when
  the observed workflows, checks and statuses for that exact commit are terminal,
  including failure or cancellation. This is a prompt to inspect CI, never a
  green result, review receipt or permission to merge.

Existing records retain their explicit backstops and event evaluation. The
readers access only configured forge hosts;
item text cannot choose a URL or command. Failed, missing, malformed or capped
inventories remain UNKNOWN and hold the wait. Reads are deduplicated within a
candidate phase and share a twelve-request budget. All fresh pre-release reads
share a second twelve-request budget; even many rows waiting on the same fact
cannot amplify reads past those phase bounds. Exhaustion is UNKNOWN until the
next scheduled pass, with no immediate retries. Distinct forge facts rotate
through the observation budget every five-minute slot; duplicate waiters share
one read. A capacity-skipped observation keeps any prior failure count unchanged
and never counts toward the three-pass error report. Attempted reads that fail
still count. A complete workflow inventory with an active run proves the wait
is unmet without fetching statuses or checks; terminal CI still requires all
those inventories. Commit statuses paginate within the same request budget,
and repeated or capped pages remain UNKNOWN. GitHub uses the existing
`gh` credential lookup. Forgejo uses the deployment's configured
`SHANTY_FORGEJO_URL`/`FORGEJO_URL` and existing token configuration. The legacy
per-item `event:` producer registry and ASK visibility rules remain unchanged.

Controller waits use `resume_when: ruling:<item>` or
`resume_when: activation:<item>`, also with a mandatory backstop at least 24 hours
away. They require a typed comment on that exact target item, for example:

```text
resume-event-v1: activation:example-123 outcome=granted authority=administrator at=2026-11-06T03:01:00Z
```

The authority must match the comment author and be the configured administrator
or the target owner's lead from the crew card. Both the declared UTC timestamp
and the stored comment creation timestamp must follow the current canonical
deferral boundary. The comment must be recorded within five minutes of its
declared timestamp and cannot be future-dated. Free prose and quoted old rulings
do not satisfy a gate. Only `granted` meets it; a newer `denied` or `revoked`
keeps it held. Missing authority, malformed/capped metadata and read failures
remain UNKNOWN. A fresh read before release catches a later revocation. Existing
ASK visibility, human/access labels, dependency and prose gates still apply;
this event prompts lifecycle work and never runs a deployment or live writer.

Typed ruling/activation observations have their own unchanged limits of twelve
candidate reads and twelve fresh release checks per pass. Waiting-item identities
rotate every five-minute slot so a fixed prefix cannot starve later gates.
Different waiters for one target keep separate evidence because their deferral
boundaries may differ. A skipped observation stays UNKNOWN and preserves its
previous failure count without incrementing or clearing it. An admitted read
that fails still counts toward the three-pass report. Logs expose only a finite
failure stage (`binding`, `target`, `registry`, `comments`, or `markers`), never
private comment contents or transport exception text.

Natural-event conditions use `resume_when: event:<binding-id>`. Bindings live in
the reviewed `shantytown.resume_events.REGISTRY`; the marker cannot supply a
command, path, URL or query. Each binding names one item, producer, host, unit,
boot/generation, protected window and starting instant. Its producer contract
must be accepted before the binding can be used. The initial protected-recycle
binding is **disabled**: this release does not change an existing review date or
start an evidence collector.

Producer-owned waits also support `recurring-quiet:<class-hash>` and
`evidence-count:<registered-producer>>=N`, with a backstop at least 24 hours
away. A met event can wake before that reminder; an expired reminder cannot
substitute for the event. Neither condition closes work or changes policy.

`recurring-quiet:` reads the existing recurring-alarm processor's private
state, matching its 24-character class hash and linked item. A fresh
authoritative census must prove 14 continuous quiet days, or a firing newer
than the writer's recorded deferral boundary. A stale/missing census, an
unreadable state file or an ambiguous deferral boundary is UNKNOWN. The
processor still owns quiet-interval resets and recurring closure. This reader
does not poll alerts, start a collector or rewrite the processor's state.
All recurring waiters share one bounded file snapshot per sweep; the next
scheduled sweep reads again, including after a failed read.

`evidence-count:` accepts only a source-reviewed entry in
`shantytown.resume_producers.COUNTERS`. The reader must deliver a complete,
fresh observation for the registered item and corpus identity, with distinct
candidate IDs and explicit required-case coverage. Duplicate IDs, mixed
identity, missing data and read failures are UNKNOWN; insufficient count or
required coverage is not met. No production counter is registered initially:
the policy49/50 producer is a separate reviewed change. Item text cannot select
a query, command, path or URL, and retained stderr is not a counter source.
The bounded contract permits at most 10,000 candidate IDs per observation;
larger thresholds are refused before deferral writes.

Version conditions need no binding, because they test a public fact rather than
one item's producer:

- `resume_when: release:<owner>/<repo>@<tag>` is met once that GitHub release is
  published. A draft or a missing release is not met yet.
- `resume_when: installed:<tool><op><version>` is met once the tool's own
  `--version` satisfies the operator: `@` or `>=` (at least), `>`, or `==`. The
  tool must be one of `sd st quipu bobbin yupana camayoc tambo dp`, and it is run
  with a fixed argv.
- `resume_when: installed:quipu@<full40lowerhexSHA>` (also `==`) instead
  checks the configured Quipu origin's `/version` serving identity. It requires
  an exact full `git_sha` and explicit `git_dirty: false`; the local CLI,
  checkout and release version cannot satisfy this condition. Only Quipu has
  this served-SHA reader. No default origin, item-provided URL, redirect, short
  prefix or SHA ordering operator is accepted. Missing/dirty/malformed identity,
  incomplete responses and read failures stay UNKNOWN. A clean different SHA
  is not met. Long bare digit targets (seven or more digits) are ambiguous
  commit prefixes, not semver major numbers; use dotted versions for those.

`st work defer` refuses a malformed argument before writing anything. A read
that cannot answer cleanly (a network error, a tool not on PATH, a version that
does not parse) is UNKNOWN and keeps the hold. It is never reported as met.

The protected-recycle evaluator requires a complete ordered interval containing
a natural soft defer inside the nominated window, then a successful unforced
recycle after the window. An intervening manual restart or hard override
disqualifies that pair. Complete fresh evidence without a pair is NOT_MET;
missing, stale, gapped, invalid or identity-mismatched evidence is UNKNOWN.
Neither verdict releases work, even after a review date lapses. MET preserves
the existing judgment, dependency and date gates and is checked again immediately
before release; it never closes the item or waives its acceptance criteria.

The fixed evidence location is
`~/.local/state/shantytown/resume-events/<binding-id>.json`. Directory and file
must be owned by the user or root and not writable by group/others; symlinks
are refused. One read is bounded to 64 KiB and 1,000 events. Evidence must be
observed within 30 minutes, with a 14-day binding horizon. Schema 1 includes
binding identity, UTC capture/window/observation bounds, explicit complete/gaps
fields, contiguous sequence bounds, and uniquely identified typed events from
the bound generation. No evidence is cached across scheduled evaluations.
Producer owners must review the complete schema before enabling a binding.

The twenty-eighth is **help**: the rationale pages for the instructions st pushes into
panes on a timer. It exists because those messages had grown into essays — every reason
anyone might need, re-pushed every few minutes, which is exactly how the one
safety-critical sentence in them gets skipped. Cutting them to pointers only works if the
pointer resolves, so the WHY moved to a page that is read ON DEMAND rather than broadcast.
A command whose only job is to be pointed at is a real cost against the count; an
instruction nobody finishes reading is a bigger one.

The twenty-ninth is **window**: one transaction for fleet maintenance. `plan`
snapshots the live roster, input evidence, active anchors, deployed SHA and tend-timer
state; `drain` acquires the relaunch lease and pauses supervision; `clear` refuses
while any recorded pane or writer remains; `release` and `abort` restore only the
recorded roster and timer state and verify the result. A second window ID cannot
overwrite the first. Human GO/FIRE, rollback, scope-widening and destructive decisions
remain outside the command.

The thirtieth is **advise**: keep-or-cycle at a handoff ([cycle advice](cycle-advice.md)).
Normal dispatches preview repository/file/scope overlap and record a signal only
after verified delivery and custody. Claude cache-write TTLs are observed; Codex
usage timing and counters use labelled per-model retention assumptions. Missing
facts stay UNKNOWN, explicit caller judgements take precedence, and the hard
context ceilings remain authoritative. Notices include the score and cache basis.

The thirty-first is **jobs**: declared scheduled and event-driven work
(docs/jobs.md). Every recurring job used to be a sweep hard-coded into tend or
a host cron outside st, and the crons failed silently — a bare `st` a unit could
not exec, sends with no `SHANTY_ROOT` that nothing journaled, no retry, and
patrols on harness session crons that died with the session. A job file is
evaluated by the tend pass, so it inherits the root, the journal and the crash
isolation. It is a command and not a tend flag for dream's reason: "what runs,
when, and did it work" has to be readable without running supervision.

The binary is **`st`**, not `shanty`: `shanty` is Stiwi's own tmux command and ours would shadow it
on PATH. This doc said `shanty` in all 29 of its examples long after the entry point was `st`, so
every command a reader copied out of here was uninvokable — the same defect as a wrong count, in the
worse place (GitHub #8).

Two of the seventeen were RENAMED on 2026-07-19, and the count did not move — a rename is not a
new command, and the test that pins the number is what proves it:

- **`prime` -> `anchor`.** An agent's anchor is what holds it to its work; the word is the noun and
  the verb. `prime` named the *harness's* act of loading a session, and we had inherited it from the
  tool we left.
- **`mail` -> `inbox`**, because it is now a real inbox rather than a verb — see below.

If it grows a `st convoy`, a `st rig`, or a `st formula`, we've rebuilt the thing we left —
but the guard against that is now the test, not this sentence.

## Machine-readable output — five flags, not five commands

An external status bar needs a handful of values out of shantytown. It gets them as **flags on the
commands that already answer those questions**, never as new subcommands: the count is the thesis,
and "something wants to poll this" does not earn a slot.

```
$ st anchor --short
aegis-1o3g

$ st anchor --short            # empty plate
                              # (nothing on stdout, exit 0)

$ st anchor --events
2

$ st crew --count
3/9

$ st crew --governor
ok 45/50/5400 24/45/248400
# each budget is current/next-threshold/seconds-until-reset.
#   `-` in the second slot = no higher tier; `-` in the third = no reset published.
#   Neither is ever rendered as a number: a bar reading 0 would say "resets now" forever.
# both windows, because they exhaust independently and are asymmetric — and they
# refresh on completely different clocks (95 minutes vs 70 hours, measured).
# The reset is here because "throttled" and "throttled for another 1h35m" are
# different sentences to the operator: the first invites intervention, the second
# invites waiting. Seconds, not a wall-clock time — the consumer is a program, and
# it formats "resets in 1h35m" itself.
# A tier in force is NAMED after the numbers:
#   ok 70/80/5400 24/45/248400 dispatch only P0 and above [five_hour >= 70%]
# Blind cases carry NO digits, so a bar cannot scrape a stale reading:
#   lost   the signal could not be read
#   off    no governor configured

$ st anchor --harness
claude

$ st inbox --count
2
```

The contract, because a program depends on it:

- **One value on stdout, and nothing else** — no banner, no label, no colour, no trailing prose.
  Empty output means *nothing to show*; every human affordance is suppressed when the flag is passed.
- **Exit 0 even when the answer is nothing.** Errors keep the usual codes and go to **stderr**, so
  stdout stays parseable: an empty stdout with exit 0 is "nothing", with exit 2 it is "I could not
  look". Same distinction as everywhere else here.
- **`--short`, `--events` and `--harness` read exactly what `st anchor` reads** — same `$SHANTY_AGENT` resolution,
  same `--backend`/`--repo`. A status bar showing a different plate than the primer would be worse
  than no status bar.
- **`--events` never drains.** The count comes from `events.pending()`, a read that marks nothing.
  `drain()` answers the same question by *consuming* — it marks each event delivered (the BLOCK-ONCE
  rail) — so a bar polling `drain()` every few seconds would deliver the tier's stop events to a
  status bar and the administrator would never be told it had them. A read that destroys the
  delivery guarantee is the worst kind of read, and it would have looked fine.
- **`--harness` names the agent program the card runs** (harness.py). A card with no `harness`
  field prints `claude`, because that *is* the answer — an empty segment would read as "no harness".
- **`inbox --count` never marks anything read.** Same rule as `--events`, one type over: listing and
  counting are reads, and `st inbox --read` is the separate, explicit ack.
- **`--count` is `busy/total`, and total is not the roster size.** It is the number of agents whose
  busy/idle state we can actually answer; an agent that is down, has no pane, or shows a pane with no
  runtime UI is in **neither** number. Counting the unknowns into the denominator would print a
  capacity figure that was never measured, in the same font as one that was.
- **Status-bar modes read Quipu at background priority** (aegis-69x). `anchor --short/--events/--harness`,
  `crew --count/--governor/--display-snapshot`, `inbox --count`, `dashboard`, `tend` and `watch` send
  `X-Quipu-Priority: background` on every Quipu read, so a busy Quipu sheds them first with
  429 + Retry-After instead of making interactive reads wait behind them. The one list lives in
  `query_identity.BACKGROUND_INVOCATIONS`, and the one place the header is attached is
  `quipu_read_budget.open_read`, which carries reads only; writes and interactive commands
  (`st anchor`, `st work item show`, `st go`) never carry it. A shed read is UNKNOWN with its retry
  time, never an empty or green value, and further background reads skip the network until
  Retry-After expires (`quipu_busy`). The header has no effect until the server enables
  `read_admission_wait_ms`.

## What's deliberately absent

- **`st inbox` is thin, not a bus.** The default send is still one line — a tmux send-keys to an
  agent's pane. `-d/--durable` adds a *store*, and only a store: the inbox is three methods
  (deliver / unread / mark_read), with no queue, no threads, no routing, no retry, and no delivery
  daemon. A harness that grows a message *bus* is on its way to being a town. What it is NOT is
  optional plumbing: the old `mail -d` used to persist a message that nothing ever read back, onto the
  recipient's **plate**, where it evicted their actual work. The inbox is the read side and the type
  that keeps a message off the plate (`shantytown/inbox.py`), and it is pluggable — files by default,
  a real bead with `--backend beads`, and any other ticket system behind the same protocol.
- **No orchestration tier.** No mayor, deacon, witness, refinery, polecat. That tier is switched off
  on our host by directive and nothing broke — the strongest evidence we have that it isn't needed.
- **No convoys.** `gt sling` auto-creates one per dispatch. It's a write on the hot path for
  dashboard visibility. `st agent log` reads the tracker.
- **No `st handoff`.** Gas Town's drops the settings flag and silently produces a hookless
  session. If cycling a session is needed, it's `stop` then `new`, and the card carries the identity.

## Exit codes, because scripts read them

```
0   did the thing
1   refused — a precondition failed (orphan card, missing capability, unknown agent)
2   could not tell — a backend was unreachable. NOT success, NOT failure.
```

Code 2 exists because of a specific bug we shipped: a check that couldn't reach its target reported
CLEAR. **"I could not look" must never render as "fine."**
