# Starting a session

`st prime`, `st anchor` and `st attach`: what an agent reads when a session starts, and what a launch must prove. This page is part of [the CLI reference](cli.md).

## `st prime` — stack orientation

`st prime [agent]` prints the shared tool primer, then a bounded read-only crew,
anchor and lead summary. `--brief`, `--static`, `--section <prefix>` and `--json`
follow the stack contract. It reuses anchor's read resolver; it does not publish
plate state or run session hooks. The deadline returns unknown counters rather
than invented empty values. See [prime output and generated primer](prime.md).
This stack-wide orientation directive earns the forty-eighth command; `anchor`
remains the normal startup context surface.

## `st anchor` — the anchor

The anchor answers **"who am I and what do I do next"** in one call, at session start, with no
arguments. It is the single most-used thing in any agent harness — Gas Town's equivalent ran 21 times
in our measurement window — and it is the highest-leverage surface in this CLI, because *every session
starts here.*

```
$ st anchor

  You are ellie — worker, reports to malcolm.
  You own e2e test coverage.

  ON YOUR PLATE
    ▶ st-9h2  Restore the den service        (in progress, 40m)

  YOUR LEAD
    malcolm (lead) — up. Your stop events go to him.

  CONTEXT (bobbin)
    scripts/e2e/den.sh · roles/den_server/tasks/main.yml

  KNOWN (quipu)
    "auth-api was cowboy-deployed and died once before" — 2026-06-30
```

Four things, and each one has to earn its line:

1. **Identity from the card.** Not from an env var, not from a file in the workspace. One source.
2. **The work.** One item, or none. A surface that prints a backlog is a dashboard.
   When that item has no open blockers, the plate reminds the agent to record a
   `BASELINE` before a fix or improvement: time, version, probe and result,
   a success metric chosen before building, and the same probe afterwards (or
   an explanation when measurement is impossible). Dispatch carries the same
   reminder in its payload, including the dry-run preview. This is an advisory;
   it does not inspect comments, scan the board or certify a baseline exists.
3. **Where your stop events go**, and **whether that agent will receive them**. If your lead is
   unreachable, anchor says so *here* — not when you stall and discover it — and it says what
   happens next: the event RISES to the administrator with reason `lead-unreachable` and persists
   on disk. It reports the routing rather than inferring it: the destination comes from
   `tier.find_administrator` and reachability from the router's own predicate, so this line cannot
   contradict what `route_stop` will actually do. It used to, and asserted the opposite of the
   truth: workers were told their stop events went nowhere while every one of them was rising to
   the administrator as designed. `up` here means **will drain**, not "a pane answers to that name".
4. **Context and knowledge** — bobbin and quipu, first-class, and both optional. With the `none`
   adapters, those two sections vanish and anchor still works.

Startup text tells agents to check governing Directives in Quipu before acting and
record new operator directives verbatim as Directive entities through the governed
write path. This reminder appears in both anchor startup and the packaged stack
orientation, including when the plate read is unavailable. It does not perform a
graph write or grant permission to one.

A plate read refused with HTTP 429, or otherwise incomplete, returns exit 2
and an `UNKNOWN` diagnostic. `--json` also sets `availability: "unknown"` and
`error`; its `item: null` must not be treated as a known empty plate. `--short`
keeps stdout empty and uses the nonzero exit to distinguish unavailability.
No empty plate is published on this path. An observed empty plate still exits 0.

### anchor is a read. It must never write.

Gas Town's primer has a `--hook` mode that fires at SessionStart and mutates state. That coupling is
why "did I get primed?" became unanswerable when the hook silently didn't register. `st anchor` is
a pure read, safe to run twice.

st wires it into SessionStart for every role (`shantytown.session_anchor`, aegis-7edci3). That
hook runs the same render in-process and adds role startup instructions. It fires on startup,
clear and compact, and a plate it could not read is stated in one line, never rendered as
silence. "Did I get anchored?" is answerable: `st ops hooks check` verifies st's own
emitted hooks (`st-session-anchor`) alongside registered bundles, and reports MISSING, or names
the running agents that were launched without it.

If no store directory resolves, `st ops hooks check` reports CANNOT TELL and
exits 2 instead of treating zero inspected bundles as a pass. Its JSON report
retains schema `st.hook-check/1` and includes `store_error: "no store found"`.
A real, existing store with an empty registry can still pass with exit 0.

A harness with no evidence of use on the host (no running process on one of its
settings files, no card pinned to this host declaring it, no session record in
the last 24h: claude transcripts, or codex rollouts under st's role homes or the
`$XDG_STATE_HOME/shantytown/codex/<name>/sessions` store) has its `live` and
`firing` layers reported as `not-in-use` instead of `not-checked` (aegis-9uq.2).
That state is never counted as ok and never as cannot-tell, so it holds neither
exit 1 nor exit 2; its `configured` layer is still checked. A harness that does
run there keeps its verdicts: a live hook with old evidence and unreadable
activity stays `unknown` and exit 2. Unreadable crew or session stores change
nothing, so an unreadable host is never reported as "not in use". A card with
no `host` counts as use only when the deployment names no host; on a named host
it would otherwise mark its harness in use on every host.

Codex and administrator launches also deliver the same anchor render through the
verified startup input, together with any unread mail in one message. Any other
launch with an empty inbox submits this initial anchor turn too: SessionStart
context alone cannot start work. A unique completion marker verifies delivery; failed delivery
keeps mail unread and reports the missing context. This covers Remote Control
sessions where a configured SessionStart hook does not supply visible context.
The hook remains configured for subsequent session lifecycle events.

An explicit tracker `updated_at` older than 48 hours marks the plate **STALE**.
Startup then asks the agent to verify that item's current status before acting,
and to close completed work or defer/repool it as appropriate. Anchor still only
reads: age never automatically closes or reassigns work. Missing, malformed, or
timezone-free timestamps cannot establish age and do not produce a stale claim.

## `st attach` — and it starts what is down

```bash
st attach                     # the administrator (resolved from the registry), started if down
st attach weaver              # weaver's pane, started if down
st attach -r weaver           # observe only: no keystroke can land in their work
st attach weaver --no-start   # attach ONLY if already running; never create a session
```

*"weaver is down — `st crew` to see who is up"* is true, and an answer to a question nobody asked: the
operator typing `st attach weaver` has already decided they want weaver's pane. Sending them to a
second command to get there is the whole cold-start friction, so the cold-start path is one command:

```bash
st attach                     # brings up the administrator and drops you in its pane
```

`--no-start` keeps the old behaviour for the caller that needs it — a script attaching to whatever is
running must be able to promise it creates nothing. A card with **no pane** is still refused rather
than launched into an invented session: a session absent from the card is invisible to `st crew`,
`st agent stop` and `st fleet tend`.

A launch that could not be *verified* still attaches, loudly. The session exists; what could not be
established is that the runtime came up. Putting your eyes on that pane is the useful next action —
exiting instead would hide the evidence behind a second command.

## Launch verification

A live process with verified stop hooks is only the first launch check. Startup
context must also be delivered; Codex requires the adapter's observation that
this exact startup body began a turn. A stranded, queued or unobserved startup
reports `startup UNVERIFIED` and exits 2, leaving the process running and unread
inbox pointers open. Inspect the pane before retrying; do not submit unrelated
composer input. Once the exact-body Codex receipt confirms a new turn, later
terminal scrolling cannot revoke that receipt or trigger a fallback relaunch.
Codex ephemeral startup waits at most 60 seconds for the startup-anchor turn
to finish with a confirmed empty composer before typing the job. Busy timeout
or foreign/unknown composer input refuses without typing; uncertain sends are
not retried by this wait. The ordinary submission guards still run afterward.

## Graph-owned role responsibilities

When `SHANTY_RULES_QUERY` names the deployment's process-rule query, human
`st anchor` output includes the current role's responsibility summaries.
Session-start uses that same anchor render. `st fleet roles show` reads all role
scopes once and lists their summaries, including additive roles such as reviewer.
An unavailable, empty, capped or malformed read prints `UNKNOWN`; the program
never substitutes a built-in responsibility text.

The named query accepts a canonical role IRI (the namespace comes from
`SHANTY_ONTO_NS`), and `*` for the role catalogue. It returns `topic`, `rule`,
`summary`, `text`, and `scope`. Responsibilities have topic `responsibilities`
and an exact role `scope`; ordinary process rules remain in the same result.
Deployments may also accept local role names. Publish the query definition and
role-scoped rules through the deployment's governed graph lane before adoption.
The graph owns the wording; this package owns only its bounded read and render.

On the fleet-owner host, the existing `st fleet tend` pass includes an
administrator ranking check. It names each live agent whose canonical plate
is below strictly higher-priority unowned READY work, with one count/priority
comparison per agent. One shared list shows at most five unowned witnesses in
priority/rank order, followed by `+N more`. It covers unowned READY work plus
unowned P0 items in the complete active/deferred metadata projection; P0 items
outside READY are explicitly labelled. Blocked work is not
promoted to READY, and owned work is not relabeled unowned. Priority comparisons
exclude ASK-class decisions, including title-only `ASK Stiwi` items, and items
with `blocked:*` or `parked:*` labels. No assignment,
priority or rank changes automatically.

The digest includes P0 work created/closed counts for seven UTC calendar dates,
including the current partial date. This is explicitly not a rolling 168-hour
count. `SHANTY_BOARD_METRICS_QUERY` may select the aggregate query (default
`seeds_board_metrics_v1`). It must supply independent `coverage` and
`aggregation_control` rows plus reconciled `created`/`closed` grouped counts and
matching totals; capped, inconsistent or failed reads stay `UNKNOWN`. Inbox
counts do not become work counts. The aggregate has an eight-second total transport
budget; role-summary reads retain a two-second total transport budget. A single
foreground helper performs each HTTP read; the parent's monotonic deadline includes
helper startup, DNS/connection setup, headers and body consumption. Expiry kills
and reaps the helper and yields `UNKNOWN`, even if bytes keep arriving. Request
headers travel over private stdin rather than process arguments. Response and
completeness caps still apply. Neither budget changes the server deadline.
Changed actionable digests use the existing
administrator advisory route only when unowned P0 work exists; lower-priority
mismatches and unknown cohort counts do not page. Unchanged pushes remain quiet,
and failed P0 pushes remain eligible for retry. Routine healthy results remain
in the scheduled pass log, where unchanged digests repeat at most once an hour;
content changes log immediately. The separate log ledger does not acknowledge
or suppress administrator delivery. The routine advisory marker does not print
a second copy of the shared list. The pass budget may defer this
advisory sweep without interrupting supervision.

## Observed cold-launch resume condition

`resume_when: cold-launch:operator` waits for the named administrator's next
ordinary cold launch after the binding was written. Its writer provenance must
contain one valid `set_at` boundary; a missing or ambiguous boundary is UNKNOWN.
The timestamped form `cold-launch:operator@2026-11-05T21:00:00Z` still waits
from the stated UTC instant. Both accept the agent's assigned harness,
in this deployment root and host. The normal launcher records a private receipt
only after observing the live process, verifying hooks and acknowledging startup
inbox delivery. Dry runs, context-clear cycles, window restores, hold overrides,
mismatched harnesses and unverified starts cannot produce it. The sweep observes receipts;
it never starts or cycles an agent to obtain evidence. A receipt resurfaces work
before its reminder date while independent human and dependency holds remain.
It does not prove provider responses or bypass launch admission. Existing
`pr-merged:`, `ci-terminal:` and typed controller events retain their own readers
and budgets.
