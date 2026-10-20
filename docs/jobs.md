# Scheduled & event jobs

A job is recurring work declared in a file: *at 08:43 every day, tell hammond to
run the repo patrol*; *when someone outside the project opens a PR, create a
triage item and hand it to an agent*. One TOML file per job lives in
`<root>/jobs/`, and `st fleet tend` evaluates every job on each pass.

## Read Quipu declarations

The explicit graph read surface is available while signed execution is being
integrated. It does not select an execution backend or change the tend sweep:

```sh
st work jobs --graph urn:example:scheduled-jobs --expect-job urn:example:job:review list
st work jobs --graph urn:example:scheduled-jobs --expect-job urn:example:job:review --json list
st work jobs --graph urn:example:scheduled-jobs --expect-job urn:example:job:review check review
```

The graph must contain the opt-in Quechua scheduled-jobs profile: an Event links
an Action through `schema:potentialAction` and a Schedule through
`schema:eventSchedule`. The reader requires explicit RDF types, revision,
owner, host, target, enabled state, timezone, anchor and a fixed interval of at
least sixty seconds. Calendar qualifiers and ambiguous times are refused.
Disabled declarations stay visible. Multiple schedules per job require a future
explicit overlap admission and are currently refused.

`list` reports declarations, without asserting executable admission or signed
run health. `check` validates declarations and exits 2 because firing eligibility
is not yet available. `run` and `history` refuse in graph mode rather than using
local commands or local run records. An unavailable, empty, truncated or invalid
catalogue also exits 2; there is no TOML fallback. A nonempty graph alone cannot
prove every expected job exists. Repeat `--expect-job` for known identities to
make deletion of one job fail even when other declarations remain valid; without
these controls the command explicitly reports membership coverage as UNKNOWN.

For adapters in another process, put `--json` before `list` or `check`. The
versioned object contains `schema_version: 1`, the selected graph, typed `jobs`,
and explicit `UNKNOWN` runtime verdicts. `membership.required` lists only the
identity controls actually checked; `required_identities_verified` does not
claim the complete host inventory was supplied. Without controls membership
stays `UNKNOWN`. Errors emit no catalogue object and retain their nonzero exit
status; JSON without `--graph` refuses before reading local TOML.

This source capability does not load the profile into a server, register a
signing key, fire a schedule or retire an existing cron job. Calls without
`--graph` retain the existing TOML behavior below.

The source-only [seed-before-assignment library](scheduled-seeds.md) supplies
keyed creation/readback and a durable no-repeat boundary for an admitted agent
firing. It does not select an execution backend, enable a schedule, change the
catalogue reader or remove the existing tend sweep. Runtime integration and
calendar semantics remain separate.

## Why it is shaped like this

Before this, every recurring job was one of two things. Some were sweeps
hard-coded into tend. The rest were host crons, launchd agents or harness
session crons outside st, and those failed silently in every way a cron can:

- a unit that ran a bare `st` could not exec it, and failed 687 times in two
  days while the timer reported itself healthy;
- cron sends with no `SHANTY_ROOT` were never written to the send journal;
- a failure was never retried, and nobody was told;
- patrols on a harness session cron died when the session was relaunched and
  expired after seven days.

The tend pass already runs every five minutes. It has the store, the journal,
per-sweep crash isolation and a pass budget. A job evaluated there gets all of
that without extra setup. That is why `docs/features.md` still says there is
**no resident scheduler**. Nothing waits, sleeps or listens. A pass asks each job
"are you due?", runs the ones that are, records the result and exits. Every
trigger is a pull with a cursor, so a missed pass makes a job late but never
drops it.

The cost of that choice is precision. A cron job fires within one tend
interval of its slot (up to five minutes late), not on the second.

## The file

`<root>/jobs/<name>.toml`. The file name is the job's name (lowercase letters,
digits, `-`, `_`). An optional `name =` must match the file name.

```toml
description = "what this is for"   # optional
enabled = true                      # default true
host = "laptop"                     # or ["laptop", "server-1"]; default: every host with the file
timeout = "10m"                     # exec only; default 10m
catch_up = true                     # cron only; default true

[trigger]                           # exactly one of: cron, every, on, manual
cron = "43 8 * * *"                 #   ...and `when` may sit beside any of them

[action]                            # exactly one of: inbox, dispatch, exec
inbox = "hammond"
message = "run the repo-patrol skill"

[retry]                             # optional
max = 2                             # retries after the first attempt; default 2
backoff = "5m"                      # doubles each retry; default 5m
```

Validation is strict, and errors name the file and the field, for example
`bad.toml: trigger.cron: '61' is outside 0-59 in the minute field`. An unknown
key is an error, not a key that gets ignored. For example, a misspelled
`authr_not` would otherwise match every PR. A broken file never stops the other
jobs or the rest of the tend pass. It is reported on every pass, and
`st work jobs list` exits 1 while it is broken.

## Triggers

| trigger | fires | notes |
|---|---|---|
| `cron = "m h dom mon dow"` | on each matching minute, host-local time | `*`, `*/n`, `a-b`, `a-b/n`, lists, `mon`/`jan` names, `7` = Sunday. When both day-of-month and day-of-week are set, a day matches if **either** does (Vixie cron) |
| `every = "6h"` | when that long has passed since the last firing that finished | a job that has never run fires on the next pass |
| `on = "<source>"` | once per new event past the job's cursor | see below. The first pass **seeds** the cursor and fires nothing, so a new job does not dispatch the whole backlog |
| `when = "<shell>"` | alone: each time the check goes from failing to exit 0 | beside another trigger: a **guard**. A failing guard delays the firing but never cancels it |
| `manual = true` | never on its own | only `st work jobs run` fires it |

**catch_up** (cron). If the host was asleep and the pass sees a slot more than
ten minutes late, `catch_up = true` runs it once, however many slots were missed.
`catch_up = false` skips a late slot and waits for the next one.

**Event sources** (`on =`):

| source | needs | `match` keys | `{{event.*}}` fields |
|---|---|---|---|
| `gh.pr.opened`, `gh.issue.opened` | `repo = "owner/name"` | `author`, `author_not`, `title` (glob) | `number`, `title`, `author`, `url`, `repo` |
| `bead.created`, `bead.closed` | the deployment's tracker | `title` (glob), `label`, `assignee` | `id`, `title`, `status`, `assignee`, `labels` |
| `quipu.tx` | quipu configured | `source`, `actor` (glob) | `id`, `source`, `actor`, `timestamp` |

GitHub is polled with `gh pr|issue list --state all` (the newest 100), and the
cursor is the highest number seen. Beads are read once per pass for all jobs,
including closed beads. Quipu reuses the `st ops subscribe` transaction client.
If a source cannot be read, the cursor stays where it is and the job says so.
The events are delivered on a later pass, not skipped.

## Actions

Each action goes through the command it names. It is not a second
implementation of that command.

- **`inbox = "<agent>"`**, `message`, optional `durable = true`: the same code
  path as `st inbox <agent> <message>` (`-d` when durable). The text is
  prefixed `[job <name>]` so the receiving pane can tell a scheduled nudge from
  a person.
- **`dispatch = "<agent>"`** or **`dispatch = "role:<role>"`**, `title`,
  optional `body`, `labels`, `priority`: creates a work item (as `st task`
  does), then hands it over with `st go`. The job goes through the same triage
  gate, governor and pane read-back as `st go`. Like `st go`, it **must** carry
  `quipu_node = [...]` or `no_graph_context = "<why>"`, checked when the file
  loads. A role goes to the first card with that role that accepts the
  dispatch, in name order. The created item is remembered across retries, so a
  refused delivery does not create a second item.
- **`exec = "<shell>"`** or **`exec = ["argv", ...]`**: runs under `timeout`,
  with `SHANTY_ROOT`, `ST_JOB` and `ST_JOB_EVENT` (JSON) in its environment. In a
  tend pass it starts **detached** and is collected on a later pass, so a
  twenty-minute job cannot hold supervision for twenty minutes. Output goes to
  `<root>/jobs/.state/<name>.log`.

Templates use `{{date}}` (YYYY-MM-DD), `{{time}}`, `{{job}}` and `{{event.<field>}}`
(only with an `on` trigger). A field the event does not carry fails that run and
names the fields the event does have.

## Runs, retries, and who gets told

Each attempt appends one row to `<root>/logs/jobs.jsonl` with start, end, ok and
error. Per-job state (cursor, last slot, the pending queue, the last 20 runs)
lives in `<root>/jobs/.state/<name>.json`.

A failed attempt is retried after `backoff`, then `2×backoff`, `4×backoff`, and
so on, up to `retry.max` retries. After the last one the job **gives up** and
sends one durable inbox message to the administrator, naming the job, the error
and `st work jobs history <name>`. A job that retries forever hides a broken
job. A job that gives up without telling anyone is the silent cron this feature
replaces.

Hosts: a job with no `host` runs on every host whose root has the file. A job
that names hosts runs only where `[host] name` matches. On a deployment that
declares no host name, a host-scoped job does not run, because "probably this
host" is how one job ends up firing on two machines.

## The CLI

```
st work jobs [list]          every job: trigger, next due, last result, action
st work jobs check [name]    would it fire NOW, and why — reads sources, writes nothing
st work jobs run <name>      fire once now, in the foreground; recorded, never retried
st work jobs run <name> -n   print the rendered action
st work jobs history [name]  recent attempts from logs/jobs.jsonl
```

## Running tend on a Mac

`st fleet tend --install` writes a launchd agent on macOS
(`~/Library/LaunchAgents/shantytown.st-tend.plist`, `StartInterval` 300,
`RunAtLoad`) and loads it with `launchctl bootstrap`. The plist uses the
**absolute** path of the `st` you ran, sets `SHANTY_ROOT`, and carries your
shell's `PATH`, because launchd starts jobs with `/usr/bin:/bin` and tend calls
tmux, git, gh and br. It also carries `SHANTY_BACKEND`: the deployment's `[env]`
value takes precedence over the installing shell, with `files` as the standalone
default. Invalid routing configuration refuses installation before any write.
Peer governor SSH failures retain recognized causes from the final diagnostic
line, such as “No route to host”; arbitrary remote stderr is not echoed.
`--uninstall` removes it and refuses to touch a plist that
st did not write. Linux keeps the systemd user timer, unchanged.

## Examples

A daily patrol that wakes an agent. This replaces a session cron that died with
the session:

```toml
# <root>/jobs/repo-patrol.toml
description = "repo and web-mention patrol"
host = "mac"

[trigger]
cron = "43 8 * * *"

[action]
inbox = "hammond"
message = "run the repo-patrol skill"
durable = true
```

Twice a day on weekdays, retried harder because a missed patrol is a missed
reply:

```toml
# <root>/jobs/job-patrol.toml
description = "recruiter mail and LinkedIn triage"
host = "mac"

[trigger]
cron = "57 9,13 * * 1-5"

[action]
inbox = "hammond"
message = "run the job-patrol skill ({{date}})"
durable = true

[retry]
max = 3
backoff = "10m"
```

An event job that dispatches triage when someone other than the owner opens a
PR:

```toml
# <root>/jobs/pixelsrc-outside-pr.toml
description = "triage PRs from outside contributors on pixelsrc"

[trigger]
on = "gh.pr.opened"
repo = "scbrown/pixelsrc"
match = { author_not = "scbrown" }

[action]
dispatch = "hammond"
title = "triage outside PR scbrown/pixelsrc#{{event.number}}: {{event.title}}"
body = "Opened by {{event.author}}: {{event.url}}. Read it, label it, reply or route it."
no_graph_context = "outside contributions are not modelled in the graph yet"
```

## Not yet

This is a first slice. It does not yet include: `gh.release` and
`file.changed` sources; recording runs as quipu facts; or moving dream's
interval and the loose host crons (CI watch, repo audits, `hold gaming --probe`)
into job files. Each of those is a separate change.


## Store admission and terminal failure notices

Scheduled commands resolve plumbing from the deployment's
shantytown.toml [env] table before ambient environment variables.
For a Seeds board, declare SHANTY_BACKEND="seeds", exactly one of
SHANTY_SD_STORE or SHANTY_SD_QUIPU, and SHANTY_SD_PREFIX there.
QUIPU_SERVER alone identifies an ontology service, not a work board.
Shell startup files and a tmux server's global environment are insufficient
configuration for launchd or cron jobs.

The command st work jobs check [name] performs the Seeds adapter's read-only
store identity admission for enabled local durable inbox and dispatch jobs,
even when they are not due. A missing, unreachable or mismatched store exits 2.
This does not send a message, prove recipient delivery or establish complete
schedule coverage. Disabled, other-host and exec-only jobs do not trigger it.

After scheduled retries are exhausted, the CLI records one job-failed event
for the administrator through the existing local event/drain channel. This
channel does not depend on the failed work store. The event names the job,
history command and routing checks; raw action output stays in local history.
Its stable firing key prevents replay from recreating a consumed notice.
The normal administrator drain renders it as a job alert, not an agent stop or
untracked-work report. Persistence is not proof that the administrator has
received it: verify the administrator's normal local drain separately.
If no administrator or event write is available, the run reports that it could
not notify the administrator.

Before installing a delivery change, coordinate an observed installed smoke,
a test silence and a separate reader receipt. Preserve the job state, event
files (including consumed records), scheduler ledgers and canonical config
backup across rollback. Use an isolated tmux socket for source verification.
