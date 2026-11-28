# Creating and running a crew

`st fleet init`, `st fleet start` and the commands that choose each agent's program, account and host. This page is part of [the CLI reference](cli.md).

## `st fleet init` — the scaffold wizard

Agent workspaces may be plain directories or Git checkout roots. Keep-current
quietly skips an existing plain directory: it does not initialize a repository,
invent a remote, or pull a repository above that directory. Clones and linked
worktrees still get the normal fast-forward-only pull. Missing workspaces,
broken Git metadata, missing upstreams, and refused pulls remain visible errors.


Joining an existing fleet? Follow [the second-host guide](second-host.md), including
`--host`, repeatable `--peer NAME=SSH,ROOT`, `--quipu-server`,
`--ontology-namespace`, and `--canonical-source`. Host-scoped sync invocations
should retain `--require-host-sync 1` so legacy binaries reject before projecting.

A fresh clone could not reach a runnable state without hand-authoring JSON. Four artifacts had four
different origins — the store directory was a `mkdir`, the crew cards came from a hierarchy file fed to
`roles sync`, the settings files were a side effect of `roles set`, the config was hand-written — and
nothing assigned the `pane` field that every launch, attach, stop and supervise path resolves an agent
through. Ordinary `st fleet roles set` refuses an unknown agent; graph worker
registration with `--create` requires an already-configured deployment and supervisor.

```text
$ st fleet init

  st fleet init — a few questions. Enter accepts the [default].

  Administrator name (the coordinator) [admin]
  > sattler
  Worker names, comma-separated (blank for none — the admin can be alone)
  > arnold, billy
  Parent directory for agent workspaces, one dir per agent (blank = launch in the current directory)
  > /srv/crew
  Startup mode — heavy/lite (lite starts the administrator ALONE) [lite]
  >
  Hibernate the administrator? off/idle/schedule/either (off = its stop wakes it at every turn) [off]
  > idle
    Wake when this % of the answerable crew is idle [60]
  > 70
  Run NEW cards unattended (bypass harness approval prompts and sandbox)? yes/no [no]
  > no

  store    /home/you/project/.shanty
  dir      crew/
  card     sattler      administrator  pane st-sattler  workspace /srv/crew/sattler
  card     arnold       worker         pane st-arnold   workspace /srv/crew/arnold
  hooks    settings/administrator.settings.json
  config   /home/you/project/.shanty/shantytown.toml

  3 agent(s) · startup mode 'lite' · hibernate 'idle'

  Write this? [yes]
```

### Choose permissions when creating cards

`st fleet init --unattended` sets `dangerous: true` on each NEW card. This opts
those agents into their harness's approval and sandbox bypass; use it for a crew
that must run without per-command approvals. The wizard asks the same yes/no
question (default **no**), and the preview and completion output name the choice.
Without the flag or an explicit yes, cards retain manual approval prompts.

```bash
st fleet init -y --admin boss --crew ada,bo --unattended
```

The choice is stored per card, not as a global override. `--force --unattended`
only affects newly created cards; it preserves existing permission choices.
Init starts no sessions. A running agent's posture still comes from its launch.

### It writes through the existing seams, and adds none

Cards go in through the registry — which is where a card gets its generated pane. Roles and stop-hook
routing go through `tier.role_set`, the same generative operation `st fleet roles set` uses, so a crew's cards
and its hooks cannot disagree. The settings files come from the same emitter. Nothing here is a second
way to declare a crew; every artifact is one you would otherwise have written by hand, in the same
place and format.

That is also why it isn't `roles sync --interactive`: **sync projects an authority that already exists**
(the graph, or a hierarchy file) onto cards, and is idempotent against it. **init asks and creates the
authority** — including two artifacts sync has no opinion about at all, the settings files and
`shantytown.toml`. Hanging "invent a crew" off a flag of a command whose contract is *mirror what is
already declared* would make sync's most dangerous property — it overwrites cards to match a source —
reachable from a prompt.

### It never overwrites

- **An existing store is a refusal.** Cards or a config already there → exit 1, nothing written. A
  second init is far more likely to be a mistyped `--root` than an intent. `--force` says it on
  purpose, and even then **no existing card is rewritten** — an agent already carrying
  `pane: shanty-arnold` and a workspace keeps both, and only missing cards are created.
- **An existing `shantytown.toml` is kept**, never regenerated over.
- **A bad name is refused before anything is written.** Agent names become both filenames and tmux
  session names, so they're validated against the intersection (`[a-z0-9][a-z0-9_-]*`) up front rather
  than at launch. `.` and `:` are tmux address syntax and are rejected.

### It never blocks on a prompt

No terminal and no `-y` is a **refusal**, not an `input()` that hangs. A wizard that blocks forever
inside a script or a hook is worse than one that says it cannot ask.

```bash
st fleet init -y --admin boss --crew ada,bo --mode lite     # scripted: asks nothing
st fleet init -n                                            # every path it would write; writes nothing
```

A rejected answer is re-asked with the reason, and the rejection goes out on a channel *separate* from
the asking — routed through the same door it would call `input()` again and eat your next line as the
answer to a question nobody asked, shifting every later answer by one.

Finally, it **loads the config it just wrote**. A file this command emits but `st fleet start` would refuse is
the worst possible handoff.

### Generated pane names

Every card written by any path — `init`, `roles set`, `roles sync` — leaves the registry with a pane, so
it is startable immediately. The default is `st-<name>`: `shanty` is a different program on the same
PATH (the same reason the binary is `st`), and a pane prefix is how you read *whose* session a tmux row
is on a host running more than one orchestrator.

This can only ever **fill a gap** — a card that already names a pane keeps it, whatever the convention
was when it was written. A fleet whose live sessions are `shanty-*` must not have its cards repointed at
`st-*` by a projection, which would leave every card addressing a session that does not exist while the
real ones ran on.

## `st fleet start` — booting the town, by mode

One command that takes *"the crew I want tonight"* and makes it true, with an exit code that says
whether it did.

```
$ st fleet start
  mode 'lite' from the built-in defaults (no config file) — 1 agent(s): sattler

  + sattler      started      launched into 'shanty-sattler', hooks verified

  mode 'lite' · 1 selected · started 1 · 1 up · 0 fault(s)

  attach: `st attach sattler`   ·   roster: `st crew`
```

**Lite is the default, and lite is the administrator alone.** One agent's context, one agent's bill —
and the admin is the one agent that can decide who else is needed and dispatch to them. `--mode heavy`
brings up every card. A mode is a *named set* of crew in
[`shantytown.toml`](shantytown.toml.example), not a `--count`, because "how much fleet" is a decision
you make once and re-use.

```bash
st fleet start                      # the configured mode (default: lite = the admin)
st fleet start --mode heavy         # every non-retired card, admin first
st fleet start --mode night         # a mode your config defined
st fleet start billy harding        # exactly these two
st fleet start --mode heavy -n      # who WOULD start, and who is already up. launches nothing
```

### It is idempotent, and that is the whole point

`already-up` is a **success**, not a refusal, and a live agent is never launched over. The operator
who most needs a boot command is the one who does not know what is currently running — so running it
twice is not an error, and the second run launches nothing.

That is why it is not `st agent new` in a loop and not a flag on `st fleet tend`. Both of those have a guard that
is load-bearing where it is and wrong here: `new` **refuses** a live session ("never replace a live
agent"), which for a boot is exactly backwards; `tend` refuses to respawn an agent it has no launch
stamp for (another orchestrator's crew), and a cold host has no stamps for anyone.

It launches through the *same* seam as `st agent new` — workspace ensured, MCP kit provisioned, skills
linked, stop hooks verified on the live process — so an agent booted this way is not a cheaper agent.

### What it will not do

- **It will not start a `retired` agent** — not under `heavy`, not when a mode names it explicitly.
  Retirement is a deliberate, durable shutdown; `st fleet tend --unretire` is what undoes it. Every
  skipped retiree is *reported*, so silence never looks like a config line that was ignored.
- **It will not call an unverified launch a launch.** An agent whose runtime never appeared in the
  pane is `unverified`, is not counted in `up`, and the command exits 2.
- **It will not attach.** A boot that attached would block the shell that ran it, and the
  systemd/cron caller cannot afford a foreground tmux client. Attaching is `st attach`.
- **It will not partially boot on a refusal.** A bad mode, a malformed config or a name with no card
  refuses *before* launching anything: exit 1, nothing created.

Exit codes: **0** every selected agent is up · **1** refused, nothing launched · **2** the pass ran
and somebody is not known to be up.

## Creating a graph worker on this host

On an existing graph-backed deployment, register a worker before projecting its card:

```bash
st --registry quipu fleet roles set new_worker worker --create --lead supervisor --dry-run
st --registry quipu fleet roles set new_worker worker --create --lead supervisor
st fleet roles sync --dry-run
st fleet roles sync
```

Creation requires declared `QUIPU_SERVER`, `SHANTY_ONTO_NS`, and `[host] name`. The
supervisor must already be a lead or administrator. The new graph identity carries
this host's placement; the next sync projects it here and skips other hosts. An
existing local card retains its launch settings; otherwise deployment defaults apply.
Sync previews role, supervisor, host, explicit role stack, and domain. Changes to a
live agent's effective role stack or domain require `--force`, just like role or
supervisor changes. Omitted source stacks/domains/hosts preserve local values;
making an equivalent implicit stack explicit is shown but needs no force.
Sync preserves local launch and retirement settings.
The hierarchy and harness checks run before writing, and creation verifies the graph
read-back. If verification fails, inspect the graph before retrying.

`--create` refuses an existing graph identity. It registers workers; subsequent role
transitions use ordinary `roles set`. `--lead` names the new worker's supervisor;
`--reports` continues to name a lead or administrator's subordinates.

## `st fleet roles --check` — the hierarchy, verified

```
$ st fleet roles --check

  arnold      administrator  reports: malcolm         hooks: ok live: ok
  malcolm     lead           reports: ellie, ian      hooks: ok live: ok
  ellie       worker         reports_to: malcolm      hooks: ok live: ok
  dearing     worker         reports_to: —            *** ORPHAN ***

  BLOCKED: 1 agent is not correctly attached to the tier — see the reason on its row above.
```

Three outcomes: **ok**, **broken**, **cannot tell**. If it can't read a card it says so and exits
non-zero. A checker that can only report health is not a checker.

**Three legs**, each a strictly stronger question than the last:

| leg | question | column |
|-----|----------|--------|
| lines | does every agent report *somewhere*? | the verdict |
| hooks | does the **role's emitted artifact** carry the stop hooks the graph requires? | `hooks:` |
| live  | does the **process actually running in the pane** carry them? | `live:` |

The third leg exists because the second is not evidence (aegis-0v97). An artifact states
*intent*; `st` does not own every process that answers to a name in its registry. Measured on
the real store: `dearing` was `role=lead`, `lead.settings.json` emitted `[send, drain]`, and the
check was **green** — while the process in its pane had been launched by a foreign launcher with
settings carrying no stop hook at all. Seven workers routed to it and every one of their stop
events was write-only. `tmux.py` already states this rule for the kill path — *a pane NAME match
is never sufficient permission to reap*. The `live:` leg is that same rule for liveness: a name
match is never sufficient evidence of **drain**.

A **down** pane is not a fault: `route_stop` already rises to the administrator when a lead is
unreachable, loudly and with a reason. The `live:` leg catches what that path cannot see — pane
**up**, wiring **wrong**, so nothing rises and nothing drains.

## `st agent harness <agent> [target]` — retained launch preferences

Report mode lists each harness's saved model and options. Conversion archives the
outgoing explicit model and Claude Chrome preference under `harness_options`, then
selects only the target's settings. A return trip restores those values. On a first
conversion without a saved target model, use `--model <target-model>` when the
current card has an explicit model. Unsupported options are retained with a notice
and omitted from the target command. `--dry-run` writes nothing; a real conversion
backs up the card and takes effect on the next relaunch unless `--now` is chosen.
See [harness preferences](harnesses.md#and-which-model-that-program-runs) for the
card schema and named-account behavior.

## The harness — Claude Code is *a* harness, not the shape of the world

A card can name the agent program it runs:

```json
{ "role": "worker", "harness": "claude", "workspace": "/home/w" }
```

No field means `claude`, which is every card that never said otherwise, and `st anchor --harness`
prints it either way. Two are implemented — `claude` and `codex` — and a name we do not implement is
**refused**, never quietly replaced with the default: a card that asks for `opencode` and silently
gets `claude` is a launch that succeeded at being the wrong thing.

The point of the field is what it forced. The launcher hardcoded Claude Code in places that had to
agree and had no way to — the argv, the `settings.json` *format*, the artifact's **name**, the
compose invariant's literal `--settings`, the cmdline reader that looked for that same flag, and the
readback that parsed Claude Code's hook schema. Those are one decision, and codex is what proved it:
codex has **no settings flag at all**, it reads `config.toml` out of `$CODEX_HOME`. So a `Harness`
owns all of it — `launch()`, `settings()`, `settings_name()`, `render()`, `carries_settings()`,
`settings_in_cmdline()`, `read_stop_directions()`, `provision()`, `hooks()`.

Two consequences worth knowing before you put `"harness": "codex"` on a card:

- **A codex card can be a lead or an administrator.** codex's Stop hook delivers `decision: block`
  with a reason to the model, so it declares the capability the tier gates on. That reverses what
  this repo used to say, and `docs/adapters.md` carries the evidence and the version caveat.
- **`st agent new`'s liveness verify does not understand codex panes yet.** The ready-UI markers are
  Claude Code's, and a marker nobody has watched pass is not a marker — so a codex launch reports
  *could-not-tell* (2) rather than a confident wrong answer. The agent is launched; the verify is
  the part that cannot see it.

### Mixing programs across one crew

A card names its own program, and `[harness]` answers for the ones that don't:

```toml
[harness]
default = "codex"            # the fleet runs codex

[harness.by_role]
lead = "claude"              # …except the roles that receive stop events
administrator = "claude"
```

**Most specific wins: card → role → fleet → `claude`.** A card that names its program is never
moved by a config written afterwards — the table is for the silent, and a resolved default is
never written back onto the card (that would be a claim nobody made, and it would survive the
config being changed back).

Both halves are validated at load. An unimplemented harness name is refused, because a typo in
`default` moves every card in the fleet and would otherwise surface as `st agent new` failing agent by
agent. A role nobody has is refused too — a rule that applies to nobody reads as applied.

Mixed fleets work because the tier is program-blind: a codex worker sends its stop event with
`python -m shantytown.stop_event send` and a Claude Code lead drains it, since those hook commands
are shantytown's own CLI rather than either program's. The artifacts are per **(harness, role)**,
so `st fleet roles set` on a mixed crew writes `worker.settings.json` *and*
`codex/worker/config.toml`, and `st fleet roles --check` reads both formats back.

Every codex fact in the implementation was read out of codex's own source, with the file named
beside it (`shantytown/codex.py`), because a guess about another CLI's flags is exactly the kind of
code that looks shipped and has never run. The Claude Code path is pinned byte-for-byte against the
pre-split launch strings (`tests/test_harness.py`) and its emitted settings file is pinned against
the pre-codex bytes (`tests/test_codex_harness.py`).

`st crew` reports `stalled` in WORK when a live, otherwise idle agent has an
`in_progress` item at the top of its plate. The summary names these agents so
their assigned work can be resumed; they are neither free nor busy. Busy panes,
unknown observations, running background shells, holds and planned cycles keep
their existing verdicts. An unreadable assignment store makes an otherwise idle
agent unknown, rather than free. The table and `--json` use the same verdict;
`--count` excludes stalled agents from its busy/idle denominator. Plate reads
share one snapshot per roster on the br backend, including additional stores.

## Named account switching

Declare each subscription separately in `[accounts.<name>]` (see
[configuration](configuration.md#named-accounts)). `st agent account alice backup`
selects the account, its harness and its declared default model in one write.
The running process keeps its original account until the next relaunch, and the
usage census continues charging that account. Add `--model` to select a different
model available on the target subscription.

`--now` queues the change for a positively observed idle boundary, using the
existing checkpointed cycle. Busy turns, typed input, option pickers, background
shells, missing authentication, role pins, launch holds and account caps retain
the current process. The checkpoint, workspace, ownership and live-launch checks
still apply. `--dry-run` writes nothing. A deliberate stop cancels a queued change.

`--auto-failover` opts this card into supervisor switching; `--no-auto-failover`
turns it off. When its account has a proven drain or P0-only tier, tend considers
all other configured accounts with fresh headroom and a free slot. It rechecks
under the launch lock, requires a verified durable handoff, then switches at an
idle boundary. Unknown usage or handoff state waits. After an observed successful
switch, the administrator receives a durable notice. An indeterminate notice is
marked `attempting` and requires operator reconciliation instead of being sent
again on every heartbeat. No account creation or interactive login is performed.

Writable file cards are the selection authority. Graph identity may be projected
into them without clearing an existing account or explicit failover setting;
a read-only TOML registry or identity-only graph registry refuses selection writes.

Deferral summaries are serialized per deployment root and compared with the
last successfully delivered summary. Overlapping passes and identical rendered
summaries do not cause additional coordinator wakes. Failed delivery consumes
neither the finding state nor the summary, so a reachable recipient can receive
it later. A positively observed resolution re-arms a genuine later recurrence.

## Pair an existing Codex crew server

`st agent remote list [--json]` discovers per-card Codex control sockets and
reports identity, host and observed availability. `st agent remote pair NAME
[--json]` requests a short-lived manual code from that explicitly selected
existing server. `--timeout` bounds each card request (default three seconds).
Neither command launches, stops, restarts or enables a daemon. A stopped card
stays stopped; an unsupported protocol or unreadable identity stays UNKNOWN.
The commands use the same XDG/runtime home resolution as the launcher, verify
the UNIX peer against the identity-bearing daemon process, and never substitute
the ordinary Codex host or another card. Peer verification currently requires
Linux SO_PEERCRED; other platforms refuse instead of weakening routing proof.
Cards assigned to another host are never contacted; a host-assigned card also
requires the deployment's explicit local host identity. Output uses that
configured identity, leaving an undeclared host null rather than guessing it.

Pairing output is a temporary secret. Display it directly to the operator; do
not redirect it to logs, work items, inbox messages or third-party QR services.
JSON is deliberate secret-bearing output too. Provider errors never echo raw
responses. A timeout leaves issuance UNKNOWN and does not automatically retry.

This new command earns a slot because per-card pairing is an explicit action,
separate from discovery and lifecycle changes. Manual-code issuance does not
prove Android acceptance or delivery to the intended conversation. Android UI,
QR/app-link payload and reconnect after lifecycle changes remain unverified;
no QR is fabricated. Verify selected-agent delivery separately.

Use `st agent remote pair NAME --dry-run [--json]` for status/identity inspection
without issuing a code. The [phone access runbook](android-crew-sessions.md)
covers explicit card selection, expiration and unknown outcomes, permissions,
and the separate Android/reconnect acceptance checklist. Its
[dated offline record](demos/android-crew-sessions/record.md) makes the limits
of synthetic checks explicit.

## Administrator launch availability

Ordinary lifecycle commands automatically exempt a verified local
`administrator` role from routine launch governors: gaming/quiet-time holds,
usage tiers and FULL STOP/drain verdicts, account/session ceilings, pace and
burndown limits, and missing/stale usage or peer census. No `--despite-hold`
flag or global cap change is needed. This applies to `agent new`, fleet start,
attach-if-down, harness relaunch, cycles and automatic recovery. The launch
message names the exemption; `agent new --help` describes the policy.

The exact configured registry grants the role. A name, a peer process row, a
retired card or an unreadable role cannot grant it. Administrators still appear
in process and account counts and consume real quota. Workers retain their
normal limits, including the existing offline-administrator reservations.

Administrator launches serialize locally through the live-session check so two
concurrent requests cannot create duplicate sessions. An unavailable remote
worker-cap authority does not prevent local administrator recovery. In tend,
administrator recovery runs before worker admission; routine governor drains
exclude those verified administrators. Its complete roster remains
the source for accounting and wiring checks.

An exemption cannot repair missing credentials, provider authentication or
resource exhaustion, unsupported harness/model/tool settings, missing workspace
or hooks, or a malformed deployment configuration. These failures remain honest
launch failures. Explicit maintenance leases protect an in-flight operational
transaction and continue to block relaunch; they are not routine quota holds.
Deliberate stops, retirement, checkpoint-loss safeguards and per-agent operator
holds remain respected during automatic recovery. Nothing here starts a second
administrator, changes an account cap, or clears an operator hold.

## Fleet view across hosts

With `[host.peers.<name>]` entries configured, `st crew` reads each peer over SSH
and displays its agents in the same table with a `HOST` column. Each host uses
its own pane-content readiness checks. Local diagnostics follow the table.
`st crew --local` retains the local-only view and makes no peer requests.

`st crew --json` returns a versioned object with `version`, `scope`, `host`,
`complete`, `agents`, and `errors`. Each agent includes its host, name, role,
state, work verdict, posture, live flag, executing harness (card fallback), pane,
settings verdict, and tree verdict. The peer protocol requests
`st --registry files --backend files --root <peer.root> crew --json --local`
to prevent recursive polling and keep the census independent of graph and tracker
availability.
SSH connects within five seconds and each request has a twenty-second total
limit; peers are polled concurrently (up to sixteen at a time).

A failed, incompatible, or wrongly identified peer is an explicit
`<host> UNREACHABLE (<reason>)` row. Partial JSON has `complete: false` and names
the failed host in `errors`; both forms exit 2. `--count` combines the hosts'
busy/idle readings; an unreachable peer instead prints `unknown` and exits 2.
`--governor` includes remote live agents in the displayed provider occupancy,
using the local usage policy; an unreachable peer prints `lost` and exits 2.
This display does not change admission policy. Use `--local` for the previous
local count/governor behavior. `--json` cannot combine with `--count` or
`--governor`.

## Display-only roster snapshots

`st crew --display-snapshot --local --json` opts into a separate v2 display
protocol. `--count` and plain rendering are also available. Without `--local`,
the display command collects only v2 display peers; it never recurses. Ordinary
`st crew`, v1 peer collection, governor reads, review routing and mutation
admission keep their live paths.

A private per-UID cache shares one complete local observation across display
processes for at most 15 seconds, measured from the start of observation. One
reader refreshes it; concurrent readers see a fresh completed observation or
UNKNOWN. Expired, failed, incompatible, unsafe or oversized snapshots cannot
supply a current count. Refresh failures have a five-second retry backoff.
Different source versions, roots, registry cards, backends and board scopes use
separate keys. Boot changes and backwards monotonic observations invalidate
saved data. The cache is an observation, not a tracker or admission proof.

V2 JSON declares `purpose="display"`, `decision_eligible=false`, observation age
and completeness. A v1 reader rejects it. Fleet display envelopes retain each
host's age and errors; slow collection can expire earlier observations rather
than reporting them as current. The refresh producer currently uses Linux
parent-death process-group cancellation; unsupported hosts return UNKNOWN.

UI consumers must opt in explicitly and understand v2 freshness. Do not globally
replace `crew --json --local`: the v1 peer path also supplies governor and
operational decision consumers. Shanty's existing table parser expects name,
role and verdict columns; migrate its display readers through the versioned
JSON contract rather than feeding the new plain display format into that
parser. Source availability does not activate consumer migration. Acceptance
requires a comparable before/after caller and timeout window after the scoped
consumer release is authorized.

Shanty already has a cross-process disk cache: plain and count arguments use
separate keys. The measured 45-second sample saw four full reads at expired
entries (two per key), with bypass off; it did not show a per-process cache or
a same-key stampede. Its deployed version also caches failures. A v2 adapter
should share the canonical ST observation and avoid retaining it under another
independent 15-second output TTL. Check age at final rendering.
