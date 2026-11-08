# ✨ Features

- 🛖 **A town with no town hall.** No resident daemon, no broker, no message bus, no resident
  scheduler: declared jobs are evaluated by the tend pass ([`docs/jobs.md`](jobs.md)). That pass
  already runs every five minutes with the store, the journal and crash isolation, so a job gets
  all three for free instead of living in a host cron that fails silently.
  `st` is a process that runs, does one thing, and exits — including `st fleet tend`, which a systemd user
  timer (a launchd agent on macOS) starts every five minutes and which exits when its pass is over.
- 📮 **`st inbox` *is* `tmux send-keys`.** Nothing sits between you and the agent — which is exactly
  why an undeliverable message can't be quietly queued and reported as sent.
- 📋 **`st task` gives you an id.** Create work, get `st-1` back. That id is the whole reason step
  two has anything to say.
- 🎯 **`st go` is the one that matters.** Bind an item to an agent, tell them, confirm it landed,
  *then* record it. In that order, on purpose.
- 🚦 **Triage before every dispatch.** Refuse · nudge · clear · restart, judged from what the runtime
  actually prints on screen. Not a command you remember to run — `st go` consults it and refuses
  rather than interrupt a working agent.
- 🧭 **`st anchor` is a pure read.** Who you are, the one item on your plate, and whether the agent
  your stop events route to will actually receive them — `up` means *will drain*, not "a pane
  answers to that name". It never writes, and a test asserts that against the filesystem rather
  than trusting the docstring.
- 👥 **`st crew` reports work, not just liveness.** `up` is a launch fact; an agent three hours into
  a refactor and one sitting at an empty prompt both print `up`. The work column tells them apart.
- 🔀 **Stop events route up a tier.** worker → lead → administrator. A lead absorbs what it can and
  escalates what it can't; an unreachable lead does not swallow anything — the event RISES to the
  administrator with a reason, and is on disk before anyone reads it.
- 🔌 **Pluggable trackers.** A tracker is two functions. Files, beads, `br`, and Forgejo are
  available today; another backend uses the *same dispatch code*, proven by swap tests rather
  than by an interface alone.
- 🤖 **Bring your own agent program.** Claude Code is *a* harness, not the shape of the world —
  `codex` ships too, and a crew can mix them: pick per card, per role, or fleet-wide. The tier is
  program-blind, so a codex worker's stop event reaches a Claude Code lead unchanged. What codex
  does *not* do yet is written down rather than discovered ([`docs/harnesses.md`](harnesses.md)).
- 🖥️ **tmux-native, socket-aware.** Bring your own panes. Named sockets are first-class, because bare
  tmux cannot see them and will confidently report every live agent as down.
- 🧪 **`--dry-run` on every writing command**, from commit one.
- 🔢 **Exit codes a script can branch on** — `0` did it · `1` refused · `2` couldn't tell. *Couldn't
  tell* is a first-class answer, never rounded up to success.
- ⚰️ **A retired agent that is still alive gets two different verdicts, not one.** `st fleet tend`
  compares when the session was born against when the card was retired: born *before* the
  decision is a `survivor` — it outlived the retirement without a respawn, which is not a fault.
  Born at or after it means something started it *after* we decided to stop it, and that is the
  alarm. When it cannot prove which, it raises the alarm rather than the reassuring one.
- 📏 **`st inbox -d` refuses an oversized body instead of truncating it.** The cap is on **bytes**,
  not characters, so prose with em dashes or arrows is longer than it looks; the refusal says so,
  reports both numbers, and subtracts the signature it adds on your behalf. Silently delivering
  the first N bytes of a message is the failure this prevents — the remaining sentence usually
  still scans, so nobody can tell it was cut.

## Newer, and easy to miss

- 🌐 **Two hosts, one fleet.** Cards carry a `host`. `st fleet roles sync` projects only the members placed
  on the host it runs on, prints who it skipped, and **never demotes or orphans the administrator**,
  on a dry run or a real one. An ephemeral `st inbox` to an agent on the other host relays through
  that host's own `st` over ssh (`[host.peers.<name>]`), or refuses by name when no peer is declared.
- 🎛️ **A governor, not a scheduler.** `[governor]` tiers hold launches when a provider window is
  spent and release them when it resets; `[session_budget]` bounds hours, items and risk per
  session; `st fleet hold gaming` pauses local launches while you use the box. All of it *asks*; none of
  it kills.
- 🧠 **Context is measured, and handoff comes before compaction.** Occupancy is read from the harness
  with UNKNOWN as a real third state, hints are advisory, and the PreCompact hook checkpoints so the
  agent returns with its hooks and its bypass intact (`st agent cycle --self`, never a bare
  `/clear`). The cycle clears the live session in place where it safely can, so an
  attached operator is never detached by one.
- 🐌 **Stalls self-heal before they escalate.** An idle worker holding an item with no change for
  `SHANTY_STALL_MIN` minutes is nudged to close or release it; the coordinator hears about it only
  if that goes unanswered.
- 🧯 **Panes have a memory ceiling.** Each launched pane runs in its own systemd scope with
  `MemoryMax`, so one runaway build kills that pane instead of a bystander, and every ceiling
  outcome is logged to a file that outlives the pane.
- 🧾 **Costs and transcripts are records.** `st work cost` reads parser-owned per-bead receipts and
  publishes them to closed beads; `st agent history` archives transcripts on the stop path and projects
  them into an indexable corpus.
- 🌿 **Worktrees, not shared checkouts.** `st repo worktree <repo>` gives each agent its own index and
  HEAD off a shared project repo, installs a commit guard in the shared checkout, and `st repo push`
  pushes `wt/<agent>` to every remote.
- 🔁 **Convert a harness in one command.** `st agent harness <agent> codex` rewrites the card and its
  hooks; codex workers get the deployment's MCP servers pre-approved so their writes are not refused
  as a lost permission.

## Work scope and budget controls

A deployment can assign a capped plate, default due dates by priority, and a
shared brief showing top-priority and coming-due work. Scheduled overdue reminders
use the same capped notification path as retained specification-change intents.

With the Seeds backend, `st work item rescope` replaces the specification and
records its version and the requester's words. Empty, layered or oversized
specifications refuse before replacement. The owner's and administrator's anchors
show an unacknowledged change; `st work item ack` records the current owner's
acknowledgement. Seeds retains the history in its Quipu store.

Scheduled specification notices require `[overdue]` settings `enabled = true`
and `spec_changes = true`. The latter defaults to false. A notifier receipt
records delivery; it does not acknowledge the specification for its owner.
The portable `sd spec-query-definition` emits the `seed_spec_awareness` query;
its definition must be registered in the receiving Quipu before named queries
can use it. Missing start-generation evidence remains UNKNOWN.

### Observed qualification

On 2026-11-08, an isolated fixture using the installed Seeds 0.11.1 binary and
Shantytown source `20555332` demonstrated a replacement at version 1, visible
unacknowledged notices in both owner and administrator anchors, then a native
ACK readback with `unacked = false`. Layered, empty and oversized replacement
attempts refused with the prior version and description unchanged. Sixteen
notification and brief controls also passed, including the 400-byte display cap,
wrong-owner acknowledgement and four- and seven-change notification queues.
These are fixture results; a deployment still needs to enable and observe its
scheduled specification notices.

### Read the governor's measurements

`st crew --governor` reports provider-window utilization, next thresholds,
seconds until reset, live agent counts and the active priority floor. Policies
can differ between Claude and Codex. Session budgets separately limit elapsed
hours, completed items and admitted actions. Gaming holds pause launches,
dispatch and respawns until the hold clears; current work is not killed.

One configured deployment's read-only snapshot on 2026-11-08 reported:

| Provider window | Utilization | Next threshold | Live agents / configured cap | Priority floor |
|---|---:|---:|---:|---|
| Claude seven-day | 84% | 85% | 2 / 15 | P1 and above |
| Codex seven-day | 100% | no higher tier | 10 / 12 | P4 and above |

The percentages and counts came from that command's provider and fleet readings.
They describe the configured policy at that observation, not a default policy
for a new installation. Five-hour readings were unavailable in this snapshot.
Spend savings and cumulative shed/resume counts were not measured. Re-run the
command for the current window and policy rather than treating these figures as
a forecast. See [the CLI reference](cli.md) for configuration and hold commands.
