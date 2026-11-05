# SPEC — one stop decision

> Status: **BUILT** (administrator chain), 2026-07-30. Written before the code, to
> keep the work honest; this line is the only edit made after it.
>
> Owner-directed (Stiwi, 2026-07-29): *"lets make sure we're writing to a cohesive
> vision with a solid UX and not hacking up around a bunch of bugs trying to fix
> something we shouldn't keep."*
>
> Beads: `internal-ref` (epic), `internal-ref` (this).
>
> **As built, three deviations worth naming.** (1) Only the ADMINISTRATOR's chain
> is unified. Worker `[send, haul]` and lead `[send, drain]` each have exactly ONE
> blocking hook, so the defect this spec is about does not exist there — folding
> them in is a one-line change with no bug behind it, left for when `haul` is
> settled (§10). (2) Rank 3 additionally requires a NON-EMPTY backlog: measured
> live, it announced a hibernation with 0 events pending, i.e. claimed to hold back
> a backlog that did not exist. (3) An unreadable own-card degrades to `worker`,
> which silently disabled both Rule Zero and hibernate — it now fails open LOUDLY,
> naming what it turned off.

## 1. The problem, measured

An agent's Stop hook is a **chain of independent commands**, and each one may
return `{"decision":"block"}` on its own. Measured from the live emitted settings:

| role | Stop chain today | can block |
|---|---|---|
| worker | `stop_event send` · `stop_event haul` · capture | haul |
| lead | `stop_event send` · `stop_event drain` · capture | drain |
| administrator | `stop_event drain` · `feed_check` · capture | drain, **feed_check** |

Nothing composes those verdicts. Three consequences, all measured:

1. **A documented config knob is inert, silently.** `[hibernate] trigger =
   "schedule"` gates the *drain*. `feed_check` (Rule Zero) blocks the same stop
   independently, so in the state hibernate exists for — crew up, work ready — the
   administrator never goes quiet and nothing says why. The operator reads the
   config, reads the docs, and watches nothing happen.

2. **The same panes are scraped up to three times in one stop.** `drain` calls
   `_liveness` per event sender, `feed_check` computes free-feedable across the
   roster, and hibernate's idle share computes it *again*. Three sweeps, three
   chances to disagree about who is busy, in one turn boundary.

3. **Two policies overlap and one of them is wrong.** Rule Zero blocks when *free
   feedable workers AND dispatchable work* coexist. Hibernate's `idle` trigger
   wakes when *≥N% of the crew is idle*. Those are the same measurement pointed at
   the same decision — and where they differ, hibernate is the one that is wrong:
   "crew idle, nothing to dispatch" is not a reason to wake a coordinator. See §5.

## 2. What this spec does NOT change

Naming the non-goals, because a consolidation that quietly widens is the thing
being guarded against.

- **Delivery mechanics.** `stop_event`'s persist/route/drain/BLOCK-ONCE and the
  busy-stop rule (an ordinary mid-flight sender's event is consumed without
  waking the recipient; governance and risen events still deliver) are
  correct and are reused verbatim, not rewritten.
- **Ownership.** st still only STOPS or RESPAWNS what it launched. Unrelated.
- **The capture hook.** `SHANTY_STOP_CAPTURE` stays a separate, appended,
  non-blocking command. It is the deployment's, not ours.
- **Rule Zero's authority.** It keeps winning over hibernate. What changes is that
  it wins *out loud*.
- **The command count.** This adds no `st` subcommand. It is hook plumbing,
  invoked as `python -m shantytown.stop_policy`, for the same reason
  `stop_event` is not a subcommand.

## 3. The decision

ONE entry point per agent, whatever its role. It performs the non-blocking side
effects, then returns exactly one verdict with exactly one reason.

```
python -m shantytown.stop_policy --root <dir>
```

**Ordered, first match wins.** The order is the specification; a reader must be
able to answer "why did my coordinator not stop?" from this list alone.

| # | condition | verdict | why this rank |
|---|---|---|---|
| 0 | *(side effect, never blocks)* route + persist my own stop event upward | — | survival before any decision; a verdict must not be able to lose the event |
| 1 | a pending event is **urgent** — a governance alert, or one that ROSE past an unreachable lead | **BLOCK**: deliver | the alert's content is "an agent is working untracked right now"; a risen event means the tier already failed once |
| 2 | **Rule Zero**: free feedable workers AND dispatchable work both exist | **BLOCK**: dispatch | there is work to hand out. Sleeping through this is the stall the gate exists to prevent, and it OVERRIDES hibernate |
| 2a | **P0 plate**: a ready P0 nobody is working on AND capacity to start it, in a state not already blocked on | **BLOCK** once: start, or re-rank/defer and say why | Rule Zero for the administrator's own plate and for ephemeral slots (§3.1). Yields to stood-down and over-capacity; overrides hibernate out loud |
| 3 | **hibernate** declines (policy on, schedule not elapsed) | **ALLOW**, loudly | nothing to dispatch and nothing urgent: quiet is correct. Says how many events stay pending |
| 4 | a **deliverable** pending event (sender not mid-flight) | **BLOCK**: deliver | the ordinary drain |
| 5 | idle because a **usage-governor tier** holds the whole queue | **ALLOW**, loudly | idle is the CORRECT state under an engaged floor — and indistinguishable from a broken feeder unless something says so |
| 6 | otherwise | **ALLOW** | |

Rank 2 above rank 3 is the whole fix: hibernate can now only fire in a state where
quiet is *correct*, and when Rule Zero overrides it the output says so by name
instead of the knob appearing broken.

Rank 5 is below the event ranks deliberately: a throttled queue is no reason to
sit on somebody's undelivered report, so a capacity hold must never become a way
for the coordinator to stop hearing from its crew. And rank 2's `dispatchable`
now means *passes the governor's priority floor* — computed by the governor's own
`Verdict.admits`, the resolver `st go` gates on, so the gate can no longer demand
a dispatch that dispatch will refuse.

### 3.1 Rank 2a — the P0 plate (aegis-c01c.1)

Measured 2026-10-28 on the Mac: the only crew member was busy, ~10 P0s sat
unstarted, and the administrator's stop was **allowed** — Rule Zero only sees
*(free crew) × (unassigned ready work)*, so the administrator's own plate and
its own in-flight work were invisible. Stiwi: *"you keep stopping when there is
much work to do."*

**The plate.** READY items (open, unblocked — the tracker's own readiness read,
scoped to the administrator and unassigned work) with priority 0, not deferred
into the future, owned by nobody or by the administrator, and passing
`feed_check.dispatchable`'s exclusions (epic, `parked:*`, `feed:manual`,
message, ASK, decision-gated, unfeedable). Ordered by Seeds priority, then
rank (`protocols.rank_order`), then id; the block names the top three.
Unassigned items the governor's floor refuses are HELD, not plate — rank 5
names them, exactly as for Rule Zero; overlapping held IDs count only once.
Items labelled with a configured peer host name, or assigned to a crew card
whose declared host differs from this host, cannot start here. Ordinary labels
and unlabelled, unassigned work stay eligible. Items held by launching, live or
ending ephemeral job records are already being worked, even if the board still
shows them as unassigned. They become eligible again after teardown, unless a
retry job holds the same item.

**Capacity** is one value with three sources, so new sources plug in as a
number rather than as a new rank:

| source | starts | measured as |
|---|---|---|
| free crew | unassigned items | Rule Zero's free feedable workers (idle, unhauled) |
| ephemeral slots | unassigned items | `shantytown.ephemeral.free_slots(root)` — 0 until aegis-c01c.2 ships that module |
| self slots | the administrator's own items | `[fleet] admin_self_slots` (default 1) minus the administrator's own `in_progress` items — its in-flight (subagent) work is counted HERE, as occupancy |

A coordinator is never told to execute unassigned work itself: a self slot
starts only its own items.

**No loop.** The rank blocks ONCE per state, where the state is the
(startable ids, free crew, ephemeral slots, self slots) fingerprint, recorded in
`<root>/stop-policy/<agent>.p0.json` after the block. A later stop over the
**same** state falls through to ranks 3–6 (so hibernate and event delivery
behave as if the plate were empty) and the final allow names the plate as
`p0-plate-unchanged`. Only relevant capacity changes re-arm it: free crew and
ephemeral slots for unassigned work, self slots for the administrator's own
work. Crew churn cannot re-arm an own-only plate. The
ledger is untouched when a rank above 2a decided (2a never looked), kept while
the plate is unchanged, and cleared when nothing is startable — a plate that
empties and refills is a new state. A missing or unreadable ledger reads as
"never judged": the worst case is one extra block, never a silent one.

**Fail-open.** A failed board read leaves the plate empty and says
`P0-plate read FAILED` on stderr; a failed ephemeral read counts 0 slots. When
no capacity is possible (no free crew, no ephemeral slots, `admin_self_slots =
0`) the board is not read at all. When Rule Zero reads the board, it includes
the administrator's scope and rank 2a reuses those rows, avoiding a second read
and a second board snapshot.

### Inputs, gathered ONCE

A mechanically idle worker is **BUSY_WAITING** for automatic feeding when its
owned work has a `defer_until` within 60 minutes of the current UTC time, including
a 60-minute grace after that gate elapses while the item remains deferred. Such
a worker is excluded from Rule Zero's free-feedable set and from automatic tend
feeds. An available open, hooked or in-progress item on the same plate still
allows that owner's existing haul to proceed. Undated and distant defers do not
reserve the worker indefinitely. Closed items, messages, anchors and decisions
do not count toward this occupancy.

Assigned `blocked:external` work reserves the same capacity when its explicit
UTC review timestamp satisfies `0 < review - now <= 24 hours`. This covers
pending CI, review and lane events beyond the older 60-minute window. Missing,
malformed or non-UTC timestamps make occupancy UNKNOWN. An expired external gate
re-evaluates capacity without opening or resuming the item. Immediate owned work
still reaches the owner's haul. The assigned-item ceiling remains a separate gate.

Dispatch candidates exclude epics by native `issue_type`, parked labels and
the governed `feed:manual` label, alongside existing owned and human/decision
exclusions. `feed:manual` means a coordinator must arrange that item's dispatch
manually; it does not bar explicit dispatch or an already-owned haul. An item
owner/coordinator applies it explicitly. Titles and embedded store names never
establish this category, and unmarked tasks stay candidates. Missing native type
metadata is UNKNOWN rather than proof of an actionable dispatch candidate; the
independent active-anchor barrier does not require this dispatch-only field.

Native Seeds reads only metadata for the mechanically idle candidate owners,
across the shared and ephemeral graphs, with existing row caps and exact-answer
checks. It never hydrates full item bodies as a fallback. Unknown occupancy
cannot prove that a worker is free: automatic feeding pauses and Rule Zero does
not block an administrator's stop on that claim. Files and configured legacy
Beads readers retain owner-scoped reads; unconfigured legacy and Forgejo
deployments retain their existing feed behavior. This filter changes no pane,
stop intent, item status, priority, explicit dispatch or account-governor rule.

One sweep of the panes, shared by every rank that needs it. This is both the
correctness property (the ranks cannot disagree about who is busy) and the
performance one.

```python
@dataclass(frozen=True)
class Inputs:
    me: str
    role: str                      # worker | lead | administrator
    pending: list[StopEvent]        # NOT consumed — a read
    liveness: dict[str, str]        # agent -> triage verdict, ONE scrape
    free_feedable: list[str]        # Rule Zero's definition, unchanged
    dispatchable: int               # Rule Zero's definition, unchanged
    hibernate: Hibernate | None     # None for every non-administrator
    minutes_quiet: float | None     # from the wake ledger
```

### Output

Exactly one of:

- `{"decision":"block","reason":"<one composed reason>"}` on stdout, exit 0
- nothing on stdout, exit 0 — the stop is allowed

Every path also writes ONE line to stderr naming the rank that decided, because
"my coordinator went quiet" and "my coordinator is wedged" are indistinguishable
otherwise.

## 4. Fail-open, and where it is NOT allowed

Any error — tmux, bd, registry, a config typo — **allows** the stop, except at
rank 0. That asymmetry is deliberate:

- **Ranks 1–5 fail open.** A hook that wedges an agent's stop on a transient `bd`
  hiccup is worse than the stall it prevents. Both `feed_check` and hibernate
  already work this way; the unified entry inherits it.
- **Rank 0 does not get to fail silently.** Persisting my own stop event is
  survival, not a decision. A failure there is reported on stderr; it must never
  be swallowed to produce a clean-looking allow.

## 5. What gets DELETED

The point of the exercise. A consolidation that only adds is not one.

| removed | why |
|---|---|
| `feed_check` as a **hook entry** | its computation becomes Rule Zero's input at rank 2. One entry, one verdict. The module keeps its free-feedable/dispatchable logic verbatim — that is the part that was right |
| `[hibernate] idle_percent` | superseded by rank 2. Rule Zero already *is* the idle policy, measured better (it asks whether work can actually be handed out, not merely whether panes look idle) |
| `[hibernate] trigger` values `idle`, `either` | leaves `off` and `schedule`. `idle` was the redundant-or-wrong one |
| `hibernate.crew_idle_share()` | the third pane sweep. Nothing needs it once rank 2 owns idleness |
| one blocking hook per agent | 2 → 1 for administrators and workers |

**Concept budget after this change:** Stop hooks per agent 3 → 2 (one decision,
one capture); independently-blocking hooks 2 → 1; hibernate config keys 3 → 2;
pane sweeps per admin stop 3 → 1.

Nothing is added: no new command, no new config file, no new env var.

## 6. Acceptance criteria

Each is a test, and each fails on today's code.

1. An administrator with a pending event, free feedable workers and dispatchable
   work **blocks**, and the reason names Rule Zero — **even with
   `trigger = "schedule"` and the schedule not elapsed.** The output states that
   hibernate was overridden, and by what.
2. The same administrator with **nothing dispatchable** and the schedule not
   elapsed **allows** the stop, emits no block payload, and leaves every pending
   event unconsumed (`pending` unchanged after the call).
3. A governance alert or a risen event **blocks** regardless of hibernate and
   regardless of Rule Zero being satisfied.
4. Exactly **one** pane sweep occurs per invocation, asserted by counting
   `capture` calls on a stub — the guard against a fourth sweep creeping back.
5. Any raised exception in ranks 1–5 **allows** the stop and emits no payload.
6. A worker's own stop event is persisted **before** any verdict is computed, and a
   verdict that blocks does not double-persist it.
7. `st ops doctor` / `roles --check` still detect an agent whose live process lacks the
   required stop wiring — the direction names change, so the wiring checker must
   be updated in the same change or it silently passes everything.

## 7. Migration

- `roles set` / `roles sync` re-emit the settings files; the new chain appears
  there. **Writing a settings file is not deploying it** — a running agent read
  `--settings` once, at launch, so the fleet must be relaunched (or was already
  down) for this to take effect. `st crew` names who is stale.
- `stop_event send|drain|haul` stay invokable. Any settings file still naming them
  keeps working, so a half-deployed fleet is degraded-but-correct rather than
  broken.
- `live_wiring` / `required_stop_directions` learn the new direction name
  alongside the old ones (criterion 7).

## 8. Fixing hibernate, concretely

Hibernate shipped 2026-07-29 with three config keys, its own module, its own
ledger store, and a pane sweep. Under §3 it needs **one key and no measurement of
its own.** This is the mapping.

### 8.1 The one behaviour an operator must understand

With rank 2 above rank 3, a hibernating administrator **sleeps through ordinary
worker reports** — and that is the feature, not a gap:

| what happened | verdict | why |
|---|---|---|
| worker finished, and there is ready work | **BLOCK** (rank 2) | someone is free and something can be handed out. Hibernate cannot suppress this |
| worker finished, and there is nothing to dispatch | **ALLOW** (rank 3) | the report is informational; there is no decision to make. It stays pending |
| an escalation, or an untracked-work alert | **BLOCK** (rank 1) | never slept on |

That is exactly the original ask — *"after the administrator has assigned hauls, I
want it to go into hibernate"* — and it is safe for one reason only: **rank 3
allows the stop without consuming anything.** The next wake sees the whole batch.

### 8.2 Config: three keys → one, plus a safety valve

```toml
# BEFORE (shipped tonight, and over-built)
[hibernate]
trigger = "idle"          # off | idle | schedule | either
idle_percent = 60
every_minutes = 30

# AFTER
[hibernate]
enabled = false
max_quiet_minutes = 60    # 0 = no heartbeat: wake only when something pushes
```

- **`trigger` with four values → `enabled` boolean.** Three of the four values
  existed to select between two measurements, and one of those measurements is
  being deleted. What is left is a yes/no.
- **`idle_percent` → deleted.** It cannot earn its keep once rank 2 exists. Walk
  the two states: *crew idle **and** work ready* → rank 2 already blocked, so the
  threshold never gets asked. *Crew idle and **nothing** to dispatch* → waking
  gains nothing, because there is nothing to hand out. There is no third state
  where the number changes an outcome.
- **`every_minutes` → `max_quiet_minutes`, renamed for what it actually is.** It is
  not a schedule to wake *on*; it is a **bound on how long a pending batch may go
  unread** when nothing else pushes. That is a real safety valve — without it, a
  fleet with no new work could leave reports pending indefinitely — so it stays,
  named honestly. `0` means "no valve", which is legitimate: `st fleet tend` pushes, and
  a push is a wake with a reason, which is always better than a timer.

### 8.3 Code: what moves and what dies

| today | after |
|---|---|
| `hibernate.crew_idle_share()` | **deleted** (the third pane sweep) |
| `hibernate.decide()` — idle branch, either branch, 5 trigger cases | **deleted**; what remains is `enabled and not stale_batch` — small enough to be rank 3 inline, so `hibernate.py` collapses into `stop_policy.py` |
| `hibernate.WakeLog` (+ `<root>/hibernate/*.json`) | **kept, shrunk**: still needed for `max_quiet_minutes`, but it records one timestamp and answers one question. No `minutes_since` arithmetic spread across callers |
| `config.Hibernate` (4 fields, 5 validators) | 2 fields, 2 validators |
| `HIB_IDLE`, `HIB_EITHER`, `HIB_TRIGGERS`, `BY_IDLE`, `wants_idle()`, `wants_schedule()` | **deleted** |
| `_hibernating()` in `stop_event.py` | **deleted**; its urgent-event carve-out becomes rank 1, which every role gets rather than only a hibernating admin |
| `cli._report_hibernate()` | kept, one line shorter |

Net for hibernate alone: **one module gone, ~120 lines gone, 3 config keys → 2,
one pane sweep → 0.** The tests move with it — the fail-open and never-consume
tests are the valuable ones and they survive verbatim, retargeted at rank 3.

### 8.4 The UX difference

```text
# TODAY — the knob appears broken, and nothing explains it
$ st fleet start --mode heavy
  hibernate 'schedule': the administrator's stop will NOT wake it until 30 min elapsed.
  ... admin never goes quiet. No output anywhere says why.

# AFTER — the override is named, at the moment it happens
  stop_policy: BLOCK (rule-zero) — 3 free feedable workers (arnold, billy, tim)
    and 11 dispatchable beads. Hibernate is enabled and was OVERRIDDEN: there is
    work to hand out.

# AFTER — and when quiet is actually correct
  stop_policy: ALLOW (hibernating) — nothing dispatchable, nothing urgent.
    4 event(s) left PENDING, unconsumed (`st anchor --events sattler` counts them).
    Next wake: a tend push, an inbox, a dispatch, or 43 min of quiet remaining.
```

## 9. The other incoherent primitives

Named here so they are tracked rather than rediscovered. **Not in this change** —
each needs its own spec — but ranked, because the ordering is the argument.

### 9.1 Config lives in seven places (highest payoff)

`env.json` · `shantytown.toml` · `settings/<role>.settings.json` ·
`crew/<name>.json` · `settings/tmux-socket` · `hierarchy.*` ·
`~/.config/shantytown/root`, plus 19 `SHANTY_*` env vars. There is no single
answer to *"where do I configure this?"*

**Fix:** one hand-edited file. `env.json` and `settings/tmux-socket` fold into
`shantytown.toml` (which already has the right shape for it); the env vars stay as
the *override* layer, not the primary one. `crew/` and `settings/` are **generated
— never hand-edited**, and should say so in their own content. `hierarchy.*` is an
*import source*, not config. The pointer is a **locator**, not config: it answers
"which deployment", which is the one thing that cannot live inside the deployment.

Result: 7 → **4**, of which exactly **1** is written by a human.
Needs a deprecation window: `env.json` is live on this fleet.

### 9.2 "Silent wrong answer" is one bug wearing eight hats

`bd --json` truncating 174 → 10 · `shanty ls` reporting no sessions with 12 live ·
doctor asserting from probes that could not have succeeded · blank plates at exit 0
· an empty registry reading as a clean bill of health. Eight open issues, one
shape: **a function that cannot distinguish "no" from "could not look" returns the
first one.**

**Fix:** the repo already has the right instinct (`CANNOT_TELL`, exit 2, the
`NOT_LIVE` sentinel) applied ad hoc per call site. Make it a **primitive** — a
small `Answer` type carrying `(value, how_measured, complete)` — and make the
truncation/absence cases *unrepresentable* rather than remembered. A lint-style
test can then pin that no adapter returns a bare collection.

### 9.3 Two definitions of "who is free"

`triage.work_state` (what `crew`/`dashboard`/`attach` render) and `feed_check`'s
free-feedable (what Rule Zero enforces) answer the same question differently — one
reads a pane, the other adds live stop-wiring and dark-crew exclusion. Rank 2
makes them agree *inside one stop*; across commands they still can't.

**Fix:** one exported liveness sweep with one verdict vocabulary, consumed by
every surface. `crew --count` already documents the right rule (unknowns in
neither number); promote it rather than reimplement it.

### 9.4 A card mixes declared and derived fields

`pane`, `role`, `reports_to` are generated; `workspace`, `dangerous`, `harness`,
`model` are declared by a human — and the write path preserves them by a
per-field `is not None` / `setdefault` convention that is correct but invisible.
Nothing states which fields a projection may overwrite.

**Fix:** one ownership table in `docs/agent-card.md`, pinned by a test over
`FilesRegistry.set`, so "would `roles sync` clobber this?" is answerable without
reading the writer.

## 10. Open, deliberately

- **Does `haul` fold into rank 2?** A worker's self-feed and a coordinator's
  dispatch gate are the same shape — "there is work, keep going" — but haul reads
  the worker's own plate while Rule Zero reads the fleet's. Left as two ranks for
  now; folding them is a follow-up with its own measurement, not a freebie.
- **Should a lead get hibernate?** No, for now: a lead's drain is how it absorbs
  its reports. Revisit only with a measured case.

## Optional admin routine-wake budget

`[admin_wake_budget]` is OFF by default. Deployments may explicitly name
participants and stage `mode = "advise"` before `mode = "enforce"`:

```toml
[admin_wake_budget]
mode = "off" # off | advise | enforce
agents = []  # explicit administrator card names
```

For named Claude administrators, the existing dispatch governor supplies fresh
account/lane evidence without advancing hysteresis. At seven-day usage >=80%,
routine Stop wakes are spaced at least five minutes apart; at >=90%, fifteen
minutes. An unknown/stale usage signal, missing wake timestamp or backward clock
cannot withhold work. Codex lanes and unnamed administrators are unchanged.

In enforce mode this explicit budget precedes ordinary Rule Zero dispatch and
hibernate; urgent governance/rose events still precede it. An ALLOW leaves pending
events unconsumed. There is no timer, process suspension or forced pane stop.
Advise mode records what would have been held but preserves the existing verdict.

`admin-wake-budget/<agent>.json` records bounded cumulative Stop outcomes and the
last observation. The separately registered UserPromptSubmit hook counts external
submissions in `<agent>.external.json` without reading prompt stdin. This includes
operator and injected-message bypasses; their individual identity is UNKNOWN.
After source adoption, `st ops provision <agent>` projects the hook only into
the selected Claude administrator's workspace, including when its role settings
predate this feature. A role-owned hook prevents a duplicate workspace hook.
Reprovisioning with mode OFF removes only this owned fallback and preserves
unrelated hooks; shared role settings are not rewritten. Confirm a natural
UserPromptSubmit observation before claiming live external-input coverage.
Missing counter files are UNKNOWN, never zero.

This bounds routine automatic Stop wakes, **not** tokens spent in an ongoing
turn, direct/operator prompts or urgent responses. Those remain bypasses and must
be included in measured spend. A step-down is cooperative at a turn boundary;
an account-level or per-request hard token ceiling is not implemented here.
Activation and changing advise to enforce are separate deployment decisions.

Rollback: set `mode = "off"` on the new version first. Before reverting to an
older version that does not recognize this table, remove the entire
`[admin_wake_budget]` table from deployment configuration, then revert the source
merge through the normal lane. Leaving even an OFF unknown table behind would
make that older version reject its configuration.

## Optional ruling-memory reminder

`[env] SHANTY_STOP_RULING_MEMORY = "1"` enables a reminder through the existing
Stop policy and worker haul seam. It is **OFF by default**; no extra hook is
installed. This is an advisory hold once per session and unchanged pending
ruling set, using the same persisted-state pattern as rank 2a. It runs alongside
the existing context advice before normal haul/policy work. Repeating Stop
without changing that set proceeds through the ordinary policy; this reminder
never requires a successful write to release the next Stop.

Only a user message whose first line is `Stiwi ruling: <choice>` or
`Stiwi decided: <choice>` qualifies (an optional `[from stiwi]` prefix is
accepted). Assistant prose, tool output, quoted examples, questions and vague
mentions do not qualify. This is an explicit attribution cue, not authentication
of the human issuer. Verify the attribution before recording it.

The reminder gives `cy record decision --chose ... --by person-stiwi --about ...
--topic ...`, shell-quoting literal values. Optional `About: <entity>` and
`Topic: <registered-topic>` lines supply those arguments. Without them the
command uses required `RULING_ABOUT` and `RULING_TOPIC` shell variables and names
what must be selected; it never invents entities or topics. Camayoc validates
these fields and fills provenance. No command is executed by the hook.

The checker reads only the hook's exact, session-bound transcript, at most 8 MiB
and 20,000 rows. It recognizes Claude messages/tool results and Codex response
items/function calls. A paired positive receipt from Quipu episode/knot or
Camayoc record tools, or a successful direct `cy record` CLI result, discharges
rulings observed before that call. Queued, refused, missing or unpaired results
do not. Composite shell commands, custom-code wrappers, out-of-session writes
and tool surfaces without a recognized receipt are unobserved; the prompt says
"no confirmed receipt", never that the graph has no record. This check does no
network reads or writes and does not verify graph contents.

Missing, malformed, mixed-session, incomplete, nonregular or over-cap transcripts
fail open as UNKNOWN. A ledger failure also fails open. Only hashes are stored
under `<root>/ruling-memory/`; a state is durably claimed before the block is
emitted. Enablement does not install the Camayoc schema or CLI, change auto-memory
settings, or establish production acceptance. Test both harnesses through their
normal Stop hooks before enabling it in a deployment.
