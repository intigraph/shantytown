# Pane states and stops

How `st` reads a pane, what each state means and how a stop is decided and recorded. This page is part of [the CLI reference](cli.md).

## Reading a pane: a dim suggestion is not queued input

Pane text is this tier's **only** liveness oracle — `st crew` and `st go` both judge from it. So a
state the pane renders ambiguously is a state the tier cannot reason about, and there was one:

```
❯ file the goldblum install role bead
```

That is either Claude Code's **dimmed placeholder** over an empty buffer (the agent is idle and
fine), or **real unsubmitted text** left by a `send-keys` whose Enter never landed (the aegis-16e
stall). `capture-pane -p` returns plain text, and the dim attribute is precisely the bit it strips —
so the two are the same bytes. It was ambiguous in **both** directions, and both cost:

* **False stall.** An administrator read the line above as a stalled dispatch and sent Enter into a
  healthy agent's pane to "un-stall" it. Enter did nothing. Only typing a literal character — which
  made the whole line vanish, because it was placeholder over an *empty* buffer — showed the agent
  had never been stuck. That is the coordinator corrupting a pane it was trying to help.
* **Hidden stall.** Symmetrically, a genuinely wedged worker reads as "just a suggestion, it's fine"
  and gets left wedged.

**The fix is to capture the bit, not to guess it.** `capture()` takes `attrs=True` (tmux `-e`) and
`triage.input_state()` judges the box on the attribute. Measured across all 18 live panes,
2026-07-20:

```
placeholder   \x1b[39m❯\xa0\x1b[2mbd ready — pick the next item\x1b[0m     <- SGR 2 = dim
real input    \x1b[38;5;246m❯\xa0\x1b[39mzzPROBEzz                        <- no SGR at all
empty         \x1b[38;5;246m❯\xa0\x1b[39m
```

`st crew` gains a fourth verdict beside `idle`/`busy`/`?`: **`queued`** — UI up, nothing in flight,
and text sitting unsubmitted. Not free, not working. It never lands on the free list, because
`send-keys` **appends** to a pane's buffer rather than replacing it: dispatching there produces one
concatenated line that is neither message. `st go` REFUSEs the same pane.

Two rules fall out, and they are the load-bearing part:

1. **Do not "fix" a suspicious pane by pressing Enter at it.** That was the defect, not the remedy.
   `queued` is a state to *report to the agent's owner*, never one to type your way out of.
   The automatic Codex recovery below is narrower: it requires a private record
   proving st injected the exact body into this same session. A human draft or
   a matching fragment of the send journal is never that proof.
2. **When the attributes are missing, the answer is `?`.** A stripped capture with text in the box
   returns `UNKNOWN`, which degrades to `?` in `st crew` and to REFUSE in `st go` — never to `idle`.
   Refusing on doubt is cheap; dispatching into a buffer you cannot see is the incident.

This is still a heuristic on somebody else's TUI rendering, and it is the *cheap* tier of the fix.
The better one is for a worker's own hook to report `idle`/`running`/`queued` into `.shanty` so the
tier reads a **fact instead of a rendering** — the Stop event is the natural carrier (aegis-w9z1).

For a new Codex message, the sender first establishes an empty composer and
writes its own body. After the paste settles, it reads fresh attributed chrome:
a busy pane gets Tab to queue that body; an idle pane gets Enter. Missing typed
input, an unreadable frame or a changed runtime withholds the first submission.
This avoids depending on a later ownership retry when Codex visually wraps
inside a word. The retry matcher remains strict and never removes word boundaries.
A visible queue is still not delivery: the durable pointer remains unread until
independent delivery or acknowledgement. This initial send does not authorize
clearing or submitting an already occupied composer.

## `auth-dead` — login expired, and the pane lies `idle` (aegis-arma)

Measured 2026-07-22: an operator re-login rotated the shared credential and **all 9 live crew went
`● Login expired · Please run /login` at once** — with the ready UI still up and the input box
empty, which is `idle` to every other predicate. So the dead fleet stayed on the free list, Rule
Zero held the coordinator's stop hostage to nine unfeedable corpses, and tend's cycle driver
prompted a saturated dead pane over and over into the very banner it could not see. Recovery was
nine by-hand `st agent stop` + `st agent new`.

Now it is a named verdict. The banner is runtime chrome, so `ClaudeRuntime.auth_dead()` owns the
markers (tail-only, trailing blanks dropped, **line-anchored** — a `grep -n` over a dead pane's
scrollback prints the banner mid-line, and a substring match would have called the grepping agent
auth-dead; measured in the session that wrote it). `work_state` takes the answer as a passed-in
flag like `ui_up`/`awaiting`; `AUTH_DEAD` outranks everything but busy/wedged (a pane genuinely
computing has working auth by construction). It falls out of `free`, out of feed_check's feedable
set, and out of the cycle driver's saturated set — one verdict, every consumer.

Recovery is **one command**: `st fleet tend --reauth`, run **after** the operator re-logs in — `/login`
in a pane is an interactive browser OAuth flow nothing can drive, so a relaunch (which re-reads
the refreshed credential) is the whole remedy. Deliberately a flag on `tend`, not an auto-heal on
the default pass: a pass cannot know whether the operator re-logged in yet, and relaunching against
a still-stale credential kill-loops the fleet. Same rule shape as `--cycle-stale`: the supervisor
*reports* (`auth-dead` is a fault, exit 2), the explicit flag *acts*. The kill honours the `st
stop` ownership guard (a name match is not permission to kill), the respawn is the same Tender path
as a normal pass, and the verify is honest about its boundary: it proves the process **came up**,
not that it is authed — the banner only shows on the first failed API call, so if the operator did
not re-log in first, the next `st crew` says so.

Two honest limits. An agent whose auth expired while *idle* shows no banner until something makes
it try an API call — detection keys on the failed turn, so a freshly-dead quiet pane still reads
`idle` until first touch. And an agent whose *response text* begins a line with the exact banner is
indistinguishable from the banner — accepted: the line anchor already refuses every quoted/grepped
form actually measured.

## `manual` — permission posture, and the agent that cannot run a command

Measured 2026-08-01: three cards carried no `dangerous`, so their agents launched in **manual
mode** — a human keystroke to approve **every** bash call. An unattended agent that needs a
keystroke per command cannot make progress *by construction*, and it reads `up`, `current` and
`busy` the whole time. One evening of that: six coordinator picker-answers across five agents, two
agents blocked simultaneously, one agent dead twice, and a permission gauntlet where each approval
only revealed the next. It was found by capturing pane footers **by hand** — the defect had been
rendered at the bottom of every one of those panes from the moment they launched.

So `st crew` grows a **posture** column, on the same principle as the settings column beside it:

| | means |
|---|---|
| `bypass` | the pane shows `⏵⏵ bypass permissions on`, or the observed launch carries Codex’s `--dangerously-bypass-approvals-and-sandbox` flag |
| `MANUAL` | live, ready UI up, readable launch, and no bypass evidence |
| `?` | no ready UI or unreadable process observation. Not rounded to either |
| `—` | not live. A down pane has no posture; what its *card* lacks is a different block |

Two things it deliberately does **not** do.

- **It reads the PANE, never the card.** `dangerous` is read at *launch*, so a card edited without a
  relaunch changes nothing about the running process — reporting the card would report a fix as
  landed while the agent is still stopped dead. This bead's own fix was verified by the footer
  flipping, and that is the only reason we know it took. Same launch-time rule the `STALE` column
  exists for, one field over.
- **Missing evidence stays unknown.** Codex has no approval footer, so an unreadable
  process cannot establish manual mode. On macOS the process reader uses native
  elapsed-time fields and PID-scoped child discovery; on Linux it retains the GNU
  probe. This does not establish settings freshness: that remains a separate check.

### The dormant half: the arming moment now asks about *both* faults

The three bad cards became visible only because they were **un-retired** that day. `retired = true`
had hidden the defect for as long as it held: a retired card is never launched, so its defect never
becomes a symptom. Un-retiring is the moment it surfaces — and it surfaced *twice over*, because
those same cards also had no `workspace` — the fault the arming pre-flight landed for, the same day.

That is not a coincidence, and it is the reason the two checks are one list rather than two gates.
`retired = true` conceals **any** launch fault, so faults accumulate silently on retired cards and
arrive together the moment one is re-armed. `launchable.launch_gaps(card)` is that list — the
workspace half is `workspace.unlaunchable()` unchanged, the permission half is `dangerous`, and the
next one belongs there too rather than in a third place.

**Only one of them may refuse**, and the asymmetry is deliberate:

| fault | at `--unretire` | why |
|---|---|---|
| no/bad `workspace` | **REFUSES** (`--force` overrides; the reason still prints) | nobody *elected* the cwd systemd handed the supervisor |
| no `dangerous` | **says it loudly, proceeds** | `dangerous` is opt-in *by design* here, and an attended agent that wants a prompt per call is making a real choice |

```
$ st fleet tend --unretire ian
  ⚠ ian carries no `dangerous`, so it launches in MANUAL MODE — a human must approve EVERY
    bash call. […] If that is deliberate, nothing here is wrong. If it is not: `dangerous` on
    the card AND a relaunch (the mode is read at launch).
  ian is tended again.
```

A gate that refused manual mode would override an election the harness deliberately offers, and
would fire on every card that simply never set the field. The defect here was never that
manual mode is impossible to *want* — it was that choosing it by accident was impossible to *see*.
So it is said at the arming moment, when a person is present and can act, and `st crew` goes on
saying it every time thereafter, which is the durable half. Retiring is never gated or warned —
only the direction that *starts* something is.

`st crew` names the same cards in its own block, so a trap that is currently harmless (the agent is
down; nothing is stalling) is still visible **before** someone walks into it. Each `Gap` carries a
short label for that column and a full sentence for the refusal: the rule is decided once, the
length is the caller's, and the two surfaces cannot end up talking about different cards.

## Deliberate-stop metrics

The crew census published by `st fleet tend` includes
`st_agents_stopped_deliberate{harness="…"}` for every observed harness. A complete
stop-store read with no deliberate stops publishes zero. An unreadable or partial
stop-store read omits that count, preserving the distinction between zero and an
unknown count. The roster census remains available independently.

## The stop decision — one verdict, five ranks

Every agent's Stop hook is **one command** that returns **one verdict with one
reason**. It was a chain of independent commands that could each block the same
stop with no shared answer; the full argument is in
[`docs/stop-policy-spec.md`](stop-policy-spec.md).

| # | condition | verdict |
|---|---|---|
| 0 | route + persist my own stop event upward | *side effect, never blocks* |
| 1 | a pending event is **urgent** — an untracked-work alert, or one that rose past an unreachable lead | **BLOCK**: deliver |
| 2 | **Rule Zero**: free feedable workers **and** dispatchable work both exist | **BLOCK**: dispatch |
| 3 | **hibernate** declines | **ALLOW**, loudly |
| 4 | a **deliverable** pending event (sender not mid-flight) | **BLOCK**: deliver |
| 5 | idle because a **governor tier** holds the whole queue | **ALLOW**, loudly |
| 6 | otherwise | **ALLOW** |

Read the order as the answer to *"why did my coordinator not stop?"* — it is
answerable from this table alone, which is the property the old chain lacked.

### Permanent referents are not haul work

Label permanent inventory or exception records `anchor`. The assigned haul,
stop-hook advance and coordinator feed list exclude that label, including when
an earlier mistaken dispatch left the record `in_progress`. A standing work
queue remains feedable unless it carries `anchor`; reserve the label for records
that have no completion state. Existing legacy coordinator title exclusions
remain, but haul exclusion uses the explicit label.

### ASK records do not enter worker hooks

The haul uses the same ASK classifier as assignment capacity: ASK labels,
a title beginning `ASK Stiwi`, or a structured `blocked:human` blocker. It skips
these records in both ready and in-progress queues, then feeds executable work.
`st go` also refuses an ASK for every crew role, including an administrator
dispatching to itself, before changing the item or sending input. Ownership,
status and visibility stay intact.

When only ASKs remain, the worker is allowed to stop. The existing durable stop
stream reports `plate blocked on human` to its lead (or normal escalation route),
once for that unchanged set of items, rather than repeatedly resuming the ASK.

### Human-only ready work is not dispatchable

The shared unfeedable predicate excludes `desk` and `needs-stiwi` labels as well
as `blocked:human` and `blocked:external`. An open, unassigned operator action
can appear in ready without being executable by a crew worker. Rule Zero and
priority advisories exclude these records; labels are matched after trimming
and case normalization. Ordinary crew work mentioning a desk in its title
remains eligible.

### `dispatchable` means *passes the priority floor*

Measured live, within sixty seconds of itself:

```
st fleet tend -n     governor  usage 57% · 50% tier · dispatch only P1 and above
st go <P2> tim refused: the usage governor's 50% tier is engaged and <bead> is P2
feed_check     RULE ZERO — 1 feedable worker IDLE and 15 DISPATCHABLE bead(s).
               Top ready: <P2>; <P2>; <P2>
```

A **blocking** stop hook was ordering a dispatch the governor forbade, and naming
as its top candidates the exact beads that would be refused. `dispatchable` meant
"open, unassigned, unblocked" and never asked whether the work could be *sent*.

Two changes, and the second is the one that matters:

1. **feed_check asks the governor.** `feed_check.throttle()` filters the ready list
   through `Verdict.admits` — the same resolver `st go` gates on, never a floor
   re-derived here. A duplicated constant would be two copies of a comparison
   whose sign is already documented as a foot-gun.
2. **Rank 5 allows the stop and NARRATES it.** Under an engaged tier, an idle
   fleet with a full queue is the *correct* state — and it is observationally
   identical to a feeder that has broken. A coordinator that cannot tell them
   apart assumes the second, because that is the one it can act on.

> **The escape hatch stays.** `st go`'s refusal still ends *"or raise its priority
> if it really is that important"* — an earlier draft of this fix reworded it and
> that decision was **withdrawn** (Stiwi, on the bead). The bump is legitimate
> because it is **recorded**: `bd history` carries priority per revision with
> timestamps, so an inflation is visible and diffable after the fact. What was
> wrong was never the hatch; it was the blocking hook *herding* an automated actor
> toward it. Remove the push and a re-grade becomes a judgement someone made,
> rather than one the mechanism extracted. Two known limits on that audit trail
> are tracked separately — history entries read `Author: beads` (so *who* bumped is
> not recorded), and `bd compact`/`flatten` can squash the trail away.

`st crew` shows the same fact on the roster: a free agent under an engaged floor
is **THROTTLED-IDLE**, which is not the same failure as an agent nobody fed — and
Rule Zero exists to catch the second. It is evaluated only when somebody is free,
so a saturated fleet pays nothing for it, and it fails to silence on any error.

**Ranks 1–5 fail open.** Any error — tmux, bd, a config typo — allows the stop; a
hook that wedges an agent on a transient hiccup is worse than the stall it
prevents. Rank 0 does not get to fail *silently*: persisting your own stop event is
survival, not a decision, so a failure there is reported rather than swallowed into
a clean-looking allow.

The receiving drain prepares its response before marking reports delivered.
If tracker reads or workflow enrichment exceed the hook deadline, the reports
remain pending for the next drain. Reports arriving during preparation stay in
the queue, and a report claimed by another drain is omitted from this response.
This reduces the interval between the delivery marker and output; it is not a
durable acknowledgement from the model, so a process failure in that final
interval still requires checking the retained event and actual model receipt.

### Hibernate

```toml
[hibernate]
enabled = false
max_quiet_minutes = 60     # 0 = only wake when something pushes
```

An administrator's Stop hook **drains**: it blocks at the end of every turn and
re-injects whatever arrived. That is what keeps a coordinator awake, and billing,
all night. In `lite` mode the shape you want is *admin comes up → assigns hauls →
goes quiet*, and going quiet is exactly what an unconditional drain prevents.

Four properties make this a policy rather than a work-loss bug:

- **Rank 2 sits above it.** Hibernate can only fire when nothing is urgent *and*
  there is nothing to hand out — and when Rule Zero overrides it, the output says
  so by name. You cannot accidentally sleep a coordinator that has work to
  dispatch.
- **It sleeps through ordinary reports, deliberately.** With nothing dispatchable,
  a *"kelly stopped"* is informational; there is no decision to make. That is the
  feature, and it is safe only because —
- **Nothing is consumed.** Rank 3 allows the stop without reaching the drain that
  marks events delivered, so the backlog is intact and the next wake sees all of
  it. Count it without consuming it: `st anchor --events sattler`.
- **It removes a self-wake, never a wake.** `st fleet tend`'s pushes, an `st inbox`, a
  dispatch, or you typing in the pane all still reach it.

`max_quiet_minutes` is **not** a schedule to wake on — it bounds how long waiting
reports may sit unread while nothing pushes. `0` disables the bound, which is a
legitimate choice: a push is a wake with a *reason*, and that beats a timer.

Leads and workers never hibernate: a lead's drain is how it absorbs its reports.

### Down on purpose is not a fault

The forcing functions above can only demand **more** dispatch, so every state where
the right answer is *stop* has to be expressible to them — otherwise the mechanism
produces the wrong instruction at exactly the moment cost control matters (GitHub
#29: an operator out of usage credits stopped nine of eleven crew on instruction and
was told, nine times, to put them back).

Three ways to say it, in increasing strength:

| | what it says | who honours it |
|---|---|---|
| `st agent stop <agent> --reason "…"` | *I stopped this one, now.* Recorded durably; **not** a retirement | `st crew` and the administrator's drain report it as deliberate. Stop hooks and idle haul feeds honour the stop stamp. The removed launch stamp keeps `st fleet tend` from respawning it; `st agent new <agent>` brings it back |
| `st fleet tend --retire <agent>` | *…and do not bring it back.* Lives on the card | `st fleet tend` never respawns it; `st fleet start` skips it; the drain never lists it |
| `[fleet] stood_down = true` | *the whole fleet is quiet by decision* | Rule Zero yields (rank 2), and the drain withholds every dispatch step |

For Codex agents, stop also terminates the card's remote-control server, updater,
and code-mode host, even when its pane is already down. Each process must have
the requested `SHANTY_AGENT` identity and a recognized executable or daemon argv;
the identity is checked again before signalling. A dry run signals nothing.

All three **announce themselves** rather than going quiet. A gate that silently
stops firing is indistinguishable from a gate that is broken, which would be a worse
version of the same bug — so the drain prints what it withheld and how to undo it,
and a risen escalation still surfaces through all three. Standing a fleet down
declines to hand out work; it does not decline to *answer*.

A stop record is **cleared on relaunch**, beside the launch stamp and for the same
reason: it describes a stop that is current. One left behind would make the agent's
next real crash read as somebody's decision.

## Stop after the current turn

For opt-in, local-only stop-hook evidence collection, see
[Private stop samples](stop-samples.md). It collects a finite human-labelling set;
it never changes stop or respawn decisions.

`st agent stop <agent> --after-turn --reason 'budget hold'` persists a hold
immediately without interrupting the live turn. Haul continuation, idle feeding,
explicit dispatch and tend respawn refuse held agents. `st crew` reports who
held the agent and when. The next Stop event is persisted before a detached
invocation of the existing guarded stop removes the pane and launch stamp.
Its output is retained under `agent-holds/<agent>.stop.log` in the deployment
root; a failed stop leaves feeding held. A successful `st agent new <agent>`
clears the hold. Dry-run and ownership guards still apply.

Both immediate and after-turn stops cancel pending self-cycle requests, even
when the pane is already down (the record names a request, not a claimed
shutdown cause). Tend refuses queued cycles for stopped or held
agents and rechecks intent immediately before changing a pane. Stop and cycle
mutations are serialized per agent, so a request read before a stop cannot
relaunch it afterward. The internal stop/start fallback of a cycle retains its
request when launch fails, allowing a retry; an operator stop cancels that retry.
Explicit `st agent new` clears stop/hold intent.

Cost synchronization publishes a scheduler heartbeat before selecting an active
source. An UNKNOWN source-selection tick updates the attempt timestamp and
records `unknown_reason=source_selection`; it does not look like a stopped
schedule. The configured Camayoc publisher must support `--scheduler-only`.
Heartbeats preserve pending writes and cooldowns and never count as cost samples.
A live pane alone is insufficient source evidence: session discovery also
requires a stats event within the last hour and matching transcript metadata.

## Pane-state advice (`crew --pane-state`)

`st crew --pane-state` adds a fleet view of Jev's **inferred, advisory-only**
interpretation beside each agent's mechanical STATE and WORK. It groups names
under working, waiting-permission, login-expired, looping, idle-done, crashed,
and insufficient-evidence. `--json` returns the same rows and provenance;
`--local` skips peers. Ordinary `crew`, dispatch, recovery, tend and status-bar
counts never consult this inference.

This flag sends **redacted pane tails to an external service** (the configured
Jev provider). The fleet credential masker runs before inference; authorization
values, opaque credential-shaped strings, internal hostnames, IP addresses and
home paths are removed before truncation. Missing or failed masking refuses
inference. Capture hashes refer to redacted text only. Shape masking cannot
recognize every arbitrary secret in prose; keep secrets out of pane output.
Each host captures at most the last 60 lines / 6,000 characters per live pane,
up to 64 panes, and asks one batch of typed choices. No capture is saved or
returned in peer JSON. The response records the capture hash/time, prompt hash,
model, input-token usage, choice, confidence and probabilities. A hash identifies
the evidence; it cannot recover it later. Inspect the pane when investigating a
label. This is a point-in-time view, not proof of continuing liveness. Mechanical
WORK and the advisory are consecutive observations and may straddle a transition.

A model confidence below 0.6 becomes insufficient-evidence, retaining its raw
choice. A missing/empty pane also has insufficient evidence; absence does not
prove a crash. A failed capture, missing client/key, invalid response or timeout
is **unavailable**, not insufficient-evidence or a regex substitute: the command
retains mechanical rows, prints `JevUnavailable`, and exits 2. Older peers without
this flag are explicitly unavailable. This view cannot authorize a restart,
dispatch, permission grant, or graph promotion.

The client is Camayoc's canonical `scripts/jev.py`, loaded in an isolated worker
with a 45-second wall deadline. Its default location is
`$XDG_DATA_HOME/camayoc-src/camayoc/scripts/jev.py` (XDG defaults to
`~/.local/share`). Set `SHANTY_JEV_CLIENT` to an installed canonical client file
for other layouts. `SHANTY_PANE_MASKER` selects the fleet `mask-secrets.py`
library (default `$XDG_DATA_HOME/aegis-exec-src/scripts/mask-secrets.py`). It must
export `mask(text)`; there is no unmasked fallback. Credentials stay with that client's file-first configuration;
Shantytown does not fetch keys or add runtime dependencies. Peer commands use
their own installed client/configuration and a 65-second SSH deadline.

The labeled regression set is `tests/fixtures/pane_state_labels.json`. Run the
explicit API evaluation with:

```sh
python3 scripts/eval-pane-state.py tests/fixtures/pane_state_labels.json \
  /private/path/real-tails.json --output /private/path/pane-evaluation.json
```

Real tails must be redacted, labeled before model evaluation, and kept local.
Each input is a JSON list of `{id, label, tail}` objects. The report includes
per-label support, correct count, accuracy, precision and a confusion matrix,
including insufficient-evidence; a label with no examples has null accuracy.
Synthetic scores measure the authored set only, not fleet accuracy. Evaluation
outputs omit captures and never promote inference into a knowledge graph.

## Runtime exit with a surviving pane

A pane whose foreground process is a known login shell is a stopped runtime.
`st crew` renders it `down`, including when a refused cycle request remains
pending; JSON reports `live: false`. Old runtime UI in scrollback does not
override the process observation. The administrator's drain treats it as
stopped even when its plate still holds work. Each tend pass reports a
`runtime-exited` fault with the observed shell and leaves recovery to the
guarded lifecycle commands. Retirement and operator stop records retain their
meaning. An unreadable foreground process is insufficient evidence of exit;
an actual cycle's launch interval retains `cycling`.

## Provider safety refusals

Claude crew settings provision an asynchronous `StopFailure` command hook.
[Claude Code runs this instead of `Stop` for API errors](https://code.claude.com/docs/en/hooks#stopfailure),
so the failure is recorded without waiting for a normal turn-end hook or a pane
banner. The hook persists a `stop-failure` event with the agent, plate, error,
optional error details and rendered API message. Missing plate/request evidence
stays `UNKNOWN`; a plate read gets a two-second budget so it cannot silence
the error notice. The actual error enum used for a safeguard refusal remains
unknown until a real hook payload is observed; fixtures do not establish it.

A rendered API message containing `safeguards` takes priority over every other
error category. It records a hold for that launch and durably notifies the
agent's stop recipient, with request IDs extracted from the rendered message.
The recipient is chosen exactly as an ordinary stop's is (`route_stop`, with the
same live-lead check): the card's lead. The administrator receives it only when
the agent has no lead, when the lead is down or unreachable (the event rises and
is marked ROSE), or when the route cannot be read (a loud fallback, so a routing
read never loses the notice). That fallback covers every routing step, including the off-host lead read
from Quipu and the liveness probe: any error there still records the hold and
notifies the administrator. The scheduled `tend` safeguard reconciliation,
which only resumes a notification the hook never attempted, still reports to the
administrator.
The hold also prevents ordinary input and automatic cycles when the pane has no
banner. A human relaunch creates a fresh launch stamp; a normal successful Stop
does not clear a safeguard hold. Rate-limit and authentication failures enter the
existing `limited` and `auth-dead` supervision paths; a later successful Stop can
retire these transient signals. Other errors produce a durable inbox notice to
the same recipient. Notification work runs asynchronously with a bounded timeout and
never asks the model to continue. Launch verification checks the running
process's selected settings against its recorded launch snapshot; a newly
rewritten settings file is not proof that an old process loaded the hook.

The following pane check remains the fallback for Codex and missed hooks.
A current provider banner saying `safeguards flagged this message` or
`safeguards stopped the response` reads as `safeguard-blocked` in pane and stop
reports. Tend treats it as a fault and holds it for administrator review. It
never clears context, switches models, cycles, or sends recovery input for this
condition. Ordinary sends refuse while the banner is current.

Tend persists one administrator inbox report per observed refusal, including the
agent, request IDs when visible, and plate items (or `UNKNOWN` on a failed read).
Old scrollback, a later response, and a cleared session do not count. Missing IDs
remain `UNKNOWN`. Reports retain only metadata in `safeguard-reports/` under the
crew root; long ID/plate lists are abbreviated in the inbox and retained there.
A pending or uncertain delivery is reported loudly and never automatically
replayed: inspect its ledger and durable inbox before any manual retry. Human
review determines the next step. A saved primary hold is not delivery evidence:
tend reconciles a demonstrably absent notification attempt from the saved error
metadata, including when event persistence was interrupted and no pane banner
exists. The shared reservation still prevents replay of pending or UNKNOWN
attempts and keeps their uncertainty visible. Missing launch provenance cannot
retire a saved safety hold; only positively different known launch stamps can.

## Soft-cycle completion evidence

Runtime updates use the same idle executor for automatic checkpointed process
replacement. See [runtime update replacement](runtime-updates.md) for version
evidence, credential preflight, input deferral and serialized roll receipts.

Soft-cycle completion requires a fresh hook-reported session ID and transcript
path, plus settled ready UI and the existing permission check. A missing token
footer does not prove a reset. If the clear times out, the command reports
failure and retains the request, handoff and in-flight intent. Later passes
observe that attempt without sending another clear or restarting the continuing
turn. Missing or stale session evidence withholds a new soft clear. A delayed
clear can still execute when the turn ends; inspect the retained evidence before
any operator recovery. No active cycle is exercised by the fixture tests.

## Cycle fetch budget

An unattended cycle accepts Codex's dim `Ask Codex to do anything` prompt as
empty input. The capture must retain terminal attributes: typed text (even the
same words), mixed typed and dim text, unfamiliar suggestions and captures with
stripped attributes remain refusals. Background-shell visibility is a separate
gate; accepting the placeholder does not establish that no shells are running.

`st agent cycle` fetches and prunes only the remote selected by the workspace's
main/master upstream configuration (or its sole remote). Other remotes are not
contacted. Its loss check counts commits not found on that refreshed remote;
commits saved only on a different remote may therefore require review before cycling.
This prevents cached refs from a skipped remote from hiding deleted branches.

Set the per-tree fetch deadline in `<root>/shantytown.toml`:

```toml
[keep_current]
fetch_timeout_seconds = 180
```

The default is 180 seconds for each remote fetch in each tree, not a total
budget shared across worktrees; the value must be finite and positive. Local Git
probes retain their 60-second bound. A timeout kills the Git process group and
returns a one-line refusal without stopping the pane or changing the card or
pending cycle request. Retry after connectivity recovers or adjust the budget.
A fetch that exits with a transport error retains the existing unverified-currency
notice and loss-risk policy. Other keep-current pull paths retain their own bounds.
