---
name: dispatch-work
description: >
  Hand a work item to another agent, honestly. Use this skill when asked to
  "dispatch", "assign work to", "hand off to", "send work to", "tell agent X to
  do Y", "nudge an agent", or when you need one agent to pick up a task in
  another agent's session. Covers creating the item in any tracker, deciding
  whether the target agent's pane is ready to receive, sending via tmux, and
  verifying the message actually landed — plus the crew-coordination surfaces
  around it: watching a worker by name (`st attach`), the supervisor heartbeat
  that pushes a blocked worker to its coordinator (`st tend --loop`), and the
  cycle discipline that treats a context-saturated agent as a wall, not a target.
  Drives the shantytown `st` CLI when it is installed; falls back to a bundled
  stdlib engine over plain tmux when it isn't. Portable: shell + tmux only, no
  framework or service.
---

# Dispatch Work

Handing work to another agent is three steps:

1. **CREATE** the item in whatever tracker you use → an id
2. **SEND** the agent "go read \<id\>" → tmux send-keys
3. the agent **fetches** it itself

Most frameworks wrap this in a daemon, a queue, and a scheduler. Underneath, the
send is `tmux send-keys` and nothing more. This skill is that pattern with the
one hard part done right — deciding whether the pane is *ready*, and confirming
the message *landed*.

**Stack tools this reaches for**

| Present | This skill uses it for | Absent — what happens |
|---|---|---|
| **[shantytown](https://github.com/scbrown/shantytown)** (`st`) | **the first-class path.** Dispatch, crew state, identity, durable messages | falls back to the bundled `dispatch.py` — same triage idea, less of it |
| `tmux` | the send itself, either way | nothing works. This is the one hard requirement |
| **[bobbin](https://github.com/scbrown/bobbin)** | `st context <query>` — attach the right files to the item before you send it | dispatch a bare title; the receiving agent starts by searching |
| **[yupana](https://github.com/scbrown/yupana)** | `yupana impact <symbol>` / `yupana callers <symbol>` — attach the BLAST RADIUS to a structural item before you send it, so the receiving agent starts knowing what the change touches | dispatch names the file; the receiving agent discovers the fallout mid-edit |
| a tracker (`bd`, `gh`, files) | somewhere for the id to live | `--backend file` writes to a directory |

**Reach for `st` first.** If `st --help` answers, use it: it does everything
below and holds the identity/hierarchy state that `dispatch.py` has no place to
keep. The bundled engine exists so this skill still works on a machine where
shantytown isn't installed — not as the preferred route.

```bash
command -v st >/dev/null && echo "use st" || echo "use dispatch.py"
```

## The one rule that matters

**A send you did not verify is not a dispatch.** Sending into a pane that was
mid-response, context-exhausted, or dead is how you come to believe work was
assigned when it wasn't — the tracker says `in_progress`, the agent never saw a
thing. So the order is always:

```
triage the pane  →  (only if healthy) send  →  verify it landed  →  then record
```

Never record `in_progress` before a confirmed send. If you can't confirm, record
nothing and re-dispatch — a human chasing a dropped message beats a tracker full
of work nobody was told about.

## Dispatch a live item, not a finished one

The assignment is a **message**; the item's status is **state** — and they live in
different places. "Go do X" is durable: it sits in a pane or an inbox until read.
Marking X *done* does not retract that message. So an item finished after you
queued it — or one someone else already completed — keeps getting dispatched, and
nothing is watching the gap.

This is not hypothetical. A dispatch that fired at an already-completed item cost a
full duplicate build, found only when the second agent pushed and collided with the
first. Both agents were reasoning about the *work*; the stale thing was the
*assignment*, and you cannot check your way out of that from the receiving end. The
only place to stop it is **before the message is sent**.

So confirm the item is still open first — it is the one check the receiving agent
cannot make for you:

```bash
python3 dispatch.py send <pane> <id> --open-check 'bd show {id} --json'
```

`--open-check` runs your command (with `{id}` substituted) and refuses the dispatch
— exit 3, nothing sent — unless it exits 0. It is pluggable exactly like `create`:
give it whatever your tracker needs to say "still open" (`gh issue view {id} --json
state --jq '.state=="OPEN"'`, a grep over a status field, anything), and the tool
stays blind to what a "bead" or an "issue" is. On the `st` path the same guard is
`st go`'s refusal to dispatch an item another agent already holds — different
surface, same rule: do not send work at an item that is no longer live.

## The `st` path (preferred)

[shantytown](https://github.com/scbrown/shantytown) implements this whole
sequence as one command, and adds the two things a standalone script cannot
have: **who the agents are**, and **what each one is already holding.**

```bash
st crew                      # who exists, who is idle, who is busy
st task "Fix the ingress 502s"   # create → prints an id
st go <item> <agent>         # triage, dispatch, record — in that order
st go <item> <agent> -n      # --dry-run: shows the verdict, writes nothing
```

Its refusals are the reason to prefer it, and each is a refusal *by default*:

- **It will not type into a busy pane.** `st go` consults triage first and
  refuses rather than interrupt an agent mid-response.
- **It will not silently steal an item another agent already holds.** Dispatching
  an already-assigned item refuses unless you pass `--reassign`. A standalone
  script has no idea an item is held; `st` does, because the tracker does.
- **It will not dispatch to a *saturated* agent** — one past the cycle threshold,
  which reads idle but degrades. See the cycle discipline under *Coordinating a
  crew* below.

Exit codes (`st`'s own, and they are **not** `dispatch.py`'s — see below):

| exit | meaning |
|---:|---|
| `0` | did it |
| `1` | refused — nothing sent |
| `2` | **couldn't tell** — never rounded up to success |

The rest of the surface worth knowing here:

| Command | What it answers |
|---|---|
| `st crew` | who can take the next item. `--count` prints just `busy/total` |
| `st anchor [me]` | who am I, the one item on my plate, where my stop events go. A pure read |
| `st inbox <agent> <msg>` | a message straight into a pane — `send-keys`, nothing between |
| `st inbox <agent> <msg> -d` | **durable**: persists to the tracker *first*, then attempts the live send, so it survives a dead recipient |
| `st context <query>` | what code this item is about ([bobbin](https://github.com/scbrown/bobbin) behind it) |

**Use `-d` for anything that must survive the recipient's session dying** — a
handoff, a protocol step. Use a plain send for routine nudges. An ephemeral
message to an agent that is not there is reported as *couldn't tell*, never as
delivered.

**Attach the context, not just the title.** `st go --note-file <path>` delivers a
caveat in the *same payload* as the dispatch, so it cannot arrive after the
worker has already acted. Use `--note-file` rather than `--note` for anything
long or containing quotes — an inline double-quoted note is expanded by your
shell before `st` sees it.

**Send a pointer, not a restatement — the item is the source, your message is not.**
A dispatch generated from an item's title or summary can already be *wrong* when it
lands: a tracker's title lags its comments, so the blocker named in the body may
have been retracted in an update an hour later. A message that says "do X because
Y" freezes Y at send time; if Y has since flipped, you have sent the worker to
chase a premise that no longer holds. So dispatch "go read `<id>`, and read its
latest state" and let the worker act on the source of truth, not on your snapshot
of it. This is why the send is a pointer to the id, never a copy of its contents.

## Coordinating a crew, not just one dispatch

Dispatching one item is above. Running a *crew* — many workers, one coordinator —
needs three more moves, and `st` ships each as a feature. Check any command here
against your own `st --help` before you lean on it: a skill that documents a
surface the binary does not have is the exact drift this whole pattern exists to
avoid.

**Watch a worker by name — `st attach`.** You should never have to know which
multiplexer socket or session an agent lives on just to look at it:

```bash
st attach <agent>      # open that agent's pane — st resolves the socket + pane
st attach              # no arg: open the COORDINATOR (the administrator), the
                       # pane you most often want, which st knows from the registry
st attach <agent> -r   # --read-only: observe; no keystroke can land in their work
```

Without `st` this is `tmux attach` to the right session on the right socket —
which means knowing both, per agent. `st` removes exactly that toil by holding the
mapping. Use `-r` to *watch* a working agent without the risk of a stray keystroke
landing in its buffer.

**Never lose a blocked worker — `st tend --loop`.** A one-coordinator tier only
works if the coordinator is *told* about a stuck worker instead of polling for it.
`st tend` is the supervisor; `--loop` makes it a heartbeat:

```bash
st tend -n                 # one dry-run pass: what it WOULD respawn, touching nothing
st tend --loop 30          # a pass every 30s forever — a blocked or stalled worker is
                           # PUSHED to its coordinator within one interval, on its own
st tend --install          # the same, as a durable systemd --user timer (--interval N)
st tend --status           # is the timer installed, and when did a pass last run?
```

The load-bearing word is *pushed*: the coordinator does not sweep the crew, the
sweep comes to the coordinator. `dispatch.py` has no equivalent — it dispatches,
it does not supervise — so on the fallback path this loop is yours to run. The
rule survives the tooling either way: **the supervisor pushes; the coordinator
does not poll.**

**A stuffed agent is a wall, not a worker — the cycle discipline.** An agent deep
in context reads as *idle* — quiet pane, empty prompt — and is the single least
able to notice it should stop. `st crew` names this state `saturated` and refuses
to count it as free:

```bash
st crew    # a saturated agent shows state `saturated`, and the summary warns:
           #   ⚠ N agent(s) past the cycle threshold — NOT free, a dispatch wall
```

This is a **third** `st go` refusal, alongside busy-pane and item-stealing: `st
go` will not dispatch to a `saturated` agent, because past the cycle threshold an
agent degrades — it drops earlier context, re-derives settled decisions, and
misses constraints stated long ago. The remedy is a sequence, and its order is
load-bearing: the agent **checkpoints its state to its item, THEN clears (or hands
off to a fresh session), THEN takes new work.** Never auto-clear a saturated
agent — a bare clear discards whatever it had not yet written down. And because
the saturated agent is the least able to notice, driving the cycle is the
*coordinator's* job, not the worker's. On the fallback path this is the triage
**CLEAR** decision one notch sharper: high context is a reason to cycle before
sending, whether or not the new task is related.
## Structural changes: ask yupana BEFORE you dispatch (and before you edit)

A structural change — renaming a symbol, changing a signature, moving a module,
touching anything other code calls — has a **blast radius**, and the cheapest
moment to learn it is *before* the work starts, not when the tests break.
[yupana](https://github.com/scbrown/yupana) answers it in milliseconds from a live
code graph:

```bash
yupana impact <symbol>      # everything transitively affected by changing it
yupana callers <symbol>     # who calls it directly, and what it calls
yupana dataflow <function>  # what flows where inside it
yupana verify --file <f> --buffer <proposed>   # would this edit even resolve?
```

The dispatcher's half: run `yupana impact` on the symbols the item touches and put
the radius **in the dispatch note** — "this touches 3 files / 14 symbols, the
callers are X and Y" is the difference between a worker who plans and one who
discovers. The worker's half: run it again before the first edit, because the
graph may have moved since the dispatch.

The passive half is already wired where shantytown launches the crew: every
agent's `PreToolUse` hook runs `yupana hook pre-edit`, which sizes the edit
against per-tenant ceilings AND evaluates it against **governed policies
projected from a Quipu knowledge graph** (rules live in the graph as data;
yupana enforces them at change time; verdicts carry the rule's own rationale).
The active habit above is what the hook cannot do for you: it fires when you
edit — `yupana impact` is for *before you decide what to edit*.

Everything below is the fallback path, and the traps in it apply to `st` too —
it makes the same judgement on the same evidence.

## The bundled fallback — `dispatch.py`

For machines without shantytown. Stdlib + tmux only; run it directly, or follow
the decision tree by hand.

### Step 1 — create the item

```bash
# beads / a GitHub-compatible forge / a flat file — pick your backend:
python3 dispatch.py create "Fix the ingress 502s" --backend beads
python3 dispatch.py create "Fix the ingress 502s" --backend gh     # honours GH_HOST
python3 dispatch.py create "Fix the ingress 502s" --backend file

# any other tracker (Jira, Linear, …): give a command template that prints the id
python3 dispatch.py create "Fix it" --create-cmd 'jira new "{title}" --plain'
```

It prints the new id. The tool does **not** know what a bead or an issue is — it
needs `create(title) → id`, nothing more. That is what makes it pluggable.

### Step 2 — triage the target pane (read-only)

Before you send, look at the pane. This touches nothing:

```bash
python3 dispatch.py triage <session:win.pane> --hint "Fix the ingress 502s"
```

It prints one of four decisions **and the inputs it judged on** — because a
confident heuristic you can't inspect is worse than none:

| Decision | Meaning | What to do |
|---|---|---|
| **NUDGE** | Healthy, idle-ish. | Send it. |
| **REFUSE** | Agent is mid-response. | Wait. Sending now interrupts real work. |
| **CLEAR** | High context, unrelated to the new task. | `/clear` (or cycle) the agent first, then send. |
| **RESTART** | No session, or wedged. | Relaunch the session — see the trap below. |

#### The traps, paid for in production — they apply to `st` too

- **RESTART means relaunch from your launcher — never a "handoff"/cycle command
  that silently drops the session's hooks/settings.** A hook-less agent comes back
  looking identical to a healthy one and fails in ways you won't see. If your
  framework has a handoff that re-execs without re-registering settings, do not use
  it here.
- **A traceback is not a wedge.** Agents print errors constantly (a failing test
  prints one). Only a genuinely dead process (`[Process completed]`, `^C^C`)
  counts. Killing a working agent for printing an error is far worse than missing a
  wedge.
- **Judge the tail, not the scrollback.** A "busy" marker 20 lines up is the agent
  *talking about* a state, not being in it. The tool reads only the last few lines.
- **"running" status lies.** An agent can be `running` and parked, or `running` and
  context-dead. Verify by the PANE, never the status field. That is why triage
  reads `capture-pane`, and why it reads the runtime's own token count rather than
  guessing from screen size.

### Step 3 — send, verified

```bash
python3 dispatch.py send <session:win.pane> <item-id>
```

`send` triages first and **refuses (exit 3) unless the pane is NUDGE-healthy** —
it will not interrupt a working agent. On a healthy pane it sends, then reads the
pane back for the id; if it isn't there it exits 2 (**sent but unconfirmed —
record nothing**). Exit 0 means delivered *and confirmed*.

> ⚠️ **`dispatch.py` and `st` do not share exit codes.** `dispatch.py` is
> `0` delivered · `2` unconfirmed · `3` refused; `st` is `0` did it · `1`
> refused · `2` couldn't tell. Both keep "couldn't confirm" separate from
> success, which is the property that matters — but a wrapper that branches on
> the number must know which tool it called. Do not copy a condition from one to
> the other.

Then, and only then, record the assignment in your tracker.

## Prove it can fail

A check that has never returned red isn't a check. Every triage outcome is
exercised in `test_dispatch.py`:

```bash
python3 -m unittest    # in this skill's directory
```

To see a refusal for real: run `send` at a pane that is mid-response (its footer
shows the runtime's "esc to interrupt"/busy chrome) and watch it exit 3 without
sending. To see an unconfirmed send: target a pane and immediately clear it.

## Configure (config, not constants)

Everything tunable is an environment variable — nothing is hardcoded:

```bash
export DISPATCH_CONTEXT_HIGH_K=400          # tokens before a pane is "high context"
export DISPATCH_UNRELATED_THRESHOLD=0.15    # keyword overlap below this = unrelated
export DISPATCH_TAIL_LINES=8                # how many trailing lines triage judges
export DISPATCH_INFLIGHT="esc to interrupt|Running…"   # your runtime's busy markers
export DISPATCH_TMUX=tmux                    # tmux binary
# backend targets:
export DISPATCH_BEADS_REPO=/path/to/repo     # bd -C
export DISPATCH_GH_REPO=owner/name           # gh --repo (set GH_HOST for your forge)
export DISPATCH_FILE_DIR=./work              # where --backend file writes
```

If a marker or threshold here leaks an assumption about one runtime, override it
from the environment — don't fork the code.
