# Supervision, holds and budgets

`st fleet watch`, `st fleet tend` and `st fleet hold`: what supervision reports, what holds launches and how accounts are paced. This page is part of [the CLI reference](cli.md).

## `st fleet watch` — each administrator watches the other (aegis-az0a40)

A two-host deployment has two administrators, and until this nothing noticed when
either could not be reached. `st fleet watch` runs ONE pass from this host's
administrator against the declared peer host's:

```
st fleet watch                         probe, alert, repair, escalate; exit 0 ok · 1 down · 2 unknown
st fleet watch -n                      probe (read-only), print what it would do, write nothing
st fleet watch --metrics <textfile>    also write the Prometheus textfile (atomic)
```

Probes run cheapest first: the peer host answers ssh; the peer's own
`st crew --json --local` answers; the administrator's pane exists; its foreground
process is not a shell (and it is not wedged or auth-dead). The age of its last stop
event is reported and exported but is never a verdict: an administrator idle at its
prompt overnight is contactable.

**Unknown is not down.** A host that is asleep or off the network, or a peer st that
does not answer, proves nothing about the administrator. It never alerts, repairs or
escalates, and it is exported as `admin_peer_unknown`, never as `admin_peer_up`.

On **down**: the local administrator is told through `st inbox -d` (again at most every
`--alert-every`, 60 min); ONE relaunch per `--repair-cooldown` (30 min) runs the peer
host's own `st agent new <peer>` over the same ssh transport, and counts only if a
second probe sees the peer up; every non-ok pass is appended to
`<root>/peer-watch/log.jsonl`, and the rate-limit state lives beside it. A human is
paged through `SHANTY_ESCALATE_COMMAND` only when the repair failed or the outage has
lasted `--escalate-after` (15 min) — once per outage. A pane whose runtime exited is
down but not repairable from here (`agent new` refuses an existing session), so it
waits the threshold.

Metrics: `admin_peer_up{watcher,peer}` (1/0, absent when unknown),
`admin_peer_unknown{watcher,peer}`, `admin_peer_down_seconds{watcher,peer}`,
`admin_peer_last_activity_age_seconds{watcher,peer}` and
`admin_peer_watch_last_run_timestamp_seconds{watcher}` — the last one is what makes a
watcher that itself died visible. Arming (a timer on each host) is the deployment's step.

## Scheduled supervision: state changes and mechanical deferrals

`st fleet watch` sends one local DOWN notification per outage and one recovery
notification. A steady outage does not generate hourly reminders. `--alert-every`
now controls retries of failed DOWN and recovery delivery. Recovery observation
ends the outage immediately; pending recovery delivery cannot hide a later outage.
Each new recovery is attempted immediately even while an older send is cooling
down. Notices name the observation time and current verdict. Pending recovery
history is capped at 16 notices; coalesced older notices are counted explicitly. UNKNOWN does not reset an outage or manufacture a recovery. Repair and
human-escalation cooldowns are unchanged.

`st fleet tend` compares the full `defer_until` timestamp on every scheduled
pass: a timestamp-only recheck two hours from now stays quiet until that instant, even on the
same calendar day. Lapse messages include the full UTC timestamp. A lapsed `defer_until`
or a met `resume_when: date:...` / `resume_when: closed:...` condition can clear
both the deferred status and timestamp after a fresh tracker read. It verifies
that the item is open and the timestamp cleared. Automatic release requires a
marker-only notes (or empty notes for a timestamp-only hold), no future date,
no open blocking dependency,
and no human/external/parked hold label. Prose, ambiguous markers and met
conditions with other holds still request judgement once per state. Read errors
and indeterminate writes retry on the next pass. Three consecutive failures
produce one UNTESTABLE finding for the administrator; continued failure stays
silent after successful notification. The budget survives process restarts and
resets on recovery. An already released item is not written again. Known unmet
mechanical conditions stay held; a lapsed backstop requests an owner recheck.
Unsupported conditions request judgement even with a future timestamp.

Lapsed and condition-met deferrals notify the live item owner first, then the
owner's live lead if the owner cannot be reached. Old or missing defer provenance
and a long-overdue deadline do not by themselves escalate this notification to
the administrator. Authority gates (`ruling:` and `activation:`), binding failures,
and items whose owner and lead cannot be reached retain the administrator route.
Urgent read/release failures and tracker-store errors retain their existing
administrator routing, retry budgets and deduplication. Unknown reachability or
failed delivery cannot count as successful owner notification.

Each recipient is nudged once per unchanged item and finding state. Successful
receipts survive owner/lead reachability changes and process restarts, including
a period when both are unreachable. Failed deliveries remain retryable; a genuine
item or finding-state change rearms reminders. Existing single-recipient receipts
are retained when upgrading the ledger. A met event
can notify its owner before a future backstop; it does not clear that backstop.
Human/access/dependency holds, ASK visibility, ambiguous provenance and prose
judgement gates still prevent automatic release. The notification grants no
authority to resume, approve or mutate work. New deferrals still archive older
setter envelopes as history.

Each tend pass also writes notify/deferred-reading-list.json from the same
admitted deferred snapshot. It retains items whose updated_at is at least30days
old, including items with future deadlines, as a reading list. Age does not
judge a claim wrong or authorize release. Missing, malformed or future touch
timestamps remain listed as age UNKNOWN; an unreadable snapshot replaces the
prior report with UNKNOWN. The report names its snapshot scope and observation
time. This path adds no tracker query or pane wake, and preserves the existing
priority and hold rules.

The Stop hook consumes ordinary stop notices when their sender is currently
busy, at any age, without waking the recipient. The on-disk event remains for
audit. A later real stop creates a new notice. Urgent governance and risen
notices, waiting senders and unknown liveness remain deliverable. Only events
in the measured snapshot are discarded; a new event arriving during that check
is left for the next observation.

## Scheduled reminders in `st fleet tend`

When enabled, the shared overdue/spec/unlock notifier gets the first best-effort
slot after supervision and fleet-owner admission. A slow inbox recovery or
requested cycle cannot consume that pass's budget before reminders are admitted.
The remaining sweeps keep their saved rotation cursor; reminder admission does
not reset their progress. The existing 120-second admission budget still applies,
and no sweep already in flight is interrupted. Disabled reminders and non-owner
hosts retain their existing behavior. This adds no second schedule or resend.

A completed pass is not a delivery receipt. Check the actual notifier outcome,
recipient and delivery ID, measured body bytes, and phase latency before claiming
scheduled-delivery acceptance.

## Alert causes and members

A **cause** is the currently firing root alarm class selected from Quipu's
existing `runs_on` / `depends_on` topology. A **member** is a dependent alert
firing at the same time. Host-down plus service-down on that host is one open
work item; unrelated alerts on the same host are separate causes. Ambiguous or
unreadable topology provides no grouping authority.

The producer preserves the root's `recurring-class:<hash>` identity. The current
bridge pointer identifies the root work item, and a `Cause member:` comment
records each dependent class, target, count and onset. In Quipu the classes are
`FailurePattern` nodes: `member_of` names the root class and `tracked_by` names
its `WorkItem`. This reuses existing governed types and relationship vocabulary.

`st work item show ITEM` exposes the native parent and lifecycle state. An
existing dependent item retains its history under the root as a parent-child
member, closed with **member of cause**, not **resolved**. If the dependent alert
fires later without that root, the producer reopens its original item. Historical
parent links alone do not prove a current correlation. A member refire invalidates
old fix evidence on the root; resolving an outage still needs fix evidence and
the recurring producer's continuous-quiet gate. Membership does not broaden
Alertmanager silences or acknowledge a firing alert.

## Recovery source maintenance

A normal tend pass gives optional clone and project-worktree refreshes one shared
30-second start budget. It lets an in-flight operation finish under its existing
timeout, then defers remaining refreshes rather than interrupting Git mutations.
Tend does not run merged-topic retirement, remote landing-proof scans or branch
pruning; those remain on explicit worktree refresh commands. A stale intact
checkout must not prevent crew recovery. The account admission lock still covers
the census, governor decisions and session creation; capacity, holds and duplicate
launch checks remain in force. This budget bounds maintenance starts, not total
pass duration or the duration of runtime startup and notification sweeps.

## Gaming hold

`st fleet hold gaming` sets a persistent local manual hold; `st fleet hold gaming --clear`
clears that override without overriding a detected game. The hold refuses new
launches, replacement cycles, dispatch and tend respawns. Existing sessions stay
running; the coordinator gets a deduplicated recommendation to keep leads only
and defer heavy local work. Clearing the hold resumes normal budget policy.

Automatic detection is opt-in: `st fleet hold gaming --enable-detection`, then schedule
`st fleet hold gaming --probe` every minute using the deployment's normal scheduler.
The probe only reads process argv: the executable must be `reaper`, followed by
`SteamLaunch` and a numeric `AppId`. A Steam helper without an AppId is excluded.
The exact `fossilize_replay` executable also holds during shader compilation,
even without an AppId. Shader processes participate in activity accounting. The
hold clears only after both signals have been absent for more than two minutes
and the five-minute grace from the first launch observation has elapsed. The
first AppId after shader compilation starts a fresh five-minute launch grace. Shell
commands merely mentioning either executable do not match.

Shader evidence with no AppId is bounded at twenty minutes (`SHADER_GRACE`).
Steam runs `fossilize_replay` both as a launch precursor AND as background
library maintenance after downloads, game updates and driver changes, and the
second kind is unbounded — a measured run held a whole crew for 76 minutes with
no game running at any point. Twenty minutes covers a genuine pre-launch
precompile; past that, shader-only evidence stops holding. An AppId removes the
ceiling entirely, so a game that launches after a long precompile is held for as
long as it runs, and one appearing after the ceiling expires re-arms the hold. A probe older
than three minutes is UNKNOWN and does not enforce an automatic hold; a manual
hold remains effective. `--disable-detection` does not clear a manual override.

Every launch surface — `st agent new`, `st fleet start`, `st attach`, `st agent cycle` and the
`st agent harness --now` relaunch — takes `--despite-hold`, which overrides the hold
for that one command and says so on stderr. The hold stays in force for
everything else. Refusals print the flag with the operator's own command line
appended, so the remedy can be pasted rather than reconstructed; against an
automatic hold they say plainly that `--clear` will not help, because it removes
a manual marker only and the next probe re-asserts an automatic hold within the
minute. Dispatch (`st go`) and the feed check deliberately do NOT offer the
override: those are how an agent asks for work, and the governor exists so that
an agent cannot decide the game is over.

`st fleet hold gaming --status` is a read-only gate for local build/reindex wrappers:
exit 1 means defer, 0 means clear/off, and 2 means unknown. Never interpret 2 as
proof of absence. `--probe --metrics <path.prom>` writes an atomic textfile for
Prometheus, including hold state, probe freshness and session start. The probe
and tend both retry coordinator advisory delivery until accepted, then dedupe
repeats. Initial clear does not send a spurious session-ended notification.

GPU utilization and game-tree CPU are weak corroboration. After ten continuous
minutes at GPU <=5% and game-tree CPU <=2% of one core, the coordinator receives
`game_present_idle — game present but idle N min — your call`. This never lifts
the hold: a numeric-AppId reaper remains authoritative. Missing telemetry,
changing process identities or renewed activity reset the idle interval. A manual
hold outranks the idle advisory. Metrics retain the GPU and CPU evidence. `--probe --slowdown` applies a 25% CPU quota and CPU weight 10 to each verified
exclusive crew tmux scope, preserving stricter limits. It records original values
before applying, verifies read-back, and restores on lift without overwriting
external changes. Heavy-work wrappers are deployment integrations; this command never
modifies Steam or kills processes.

Scope ownership follows the pane's process tree and reparented runtimes whose
launch environment matches both the agent and deployment. A descendant's
protected environment does not prevent ownership proof through that ancestry.
A protected process with no matching ancestor remains unproven; the governor
refuses to change that scope's limits.

## Configurable quiet-time detectors

Declare additional holds in `<root>/shantytown.toml`; the same registry drives
launch/dispatch/tend gates, coordinator advice and exclusive crew scope quotas.
`st fleet hold all --probe --slowdown --metrics <path.prom>` samples every detector.
Schedule it every minute. The legacy `hold gaming --probe` and `--status` also
use the aggregate, so existing heavy-work wrappers honour new detectors.
One active reason keeps the hold in force even when another reason clears or
becomes UNKNOWN. With no active hold, a healthy clear detector keeps the aggregate
clear even if a peer is UNKNOWN (including before its first probe). That peer
remains UNKNOWN in diagnostics and per-reason metrics. The aggregate is UNKNOWN
only when no detector supplies a healthy observation and at least one is unknown.
`aegis_quiet_time_detector_active{reason="media"}` identifies
the cause; `aegis_quiet_time_hold_active` is the combined launch-hold decision
(full-effect detectors only). Per-reason
`aegis_quiet_time_probe_ok` and `aegis_quiet_time_probe_timestamp_seconds` expose
unavailable or stale evidence. Existing gaming metrics still describe gaming only.

Scheduled probes deliver operational hold/lift transitions to live crew panes,
separately from routine budget advice. Failed pane deliveries remain pending.
An unknown detector or failed slowdown verification warns the administrator;
a continuous hold lasting 30 minutes warns once and never clears automatically.
Before honouring a hold copied from notes, run `st fleet hold all --status`.
Each detector declares its hold `effect`. `full` (the default, and the only effect
gaming accepts) holds launches, dispatch and respawns. `no-heavy-builds` holds none of
them: agents keep launching and working, and only heavy local builds (cargo
build/test/clippy and the other heavy-work wrappers) are refused. A media session
needs only the CPU kept free; under a full hold, 20 minutes of playback refused ~15
drain jobs and stalled every PR lane. `st fleet hold all --status` exits 1 (defer
heavy work) while any hold, throttle or builds-only hold is active, and also while a
builds-only detector is UNKNOWN: builds fail closed, launches do not. The separate
gauge `aegis_quiet_time_build_hold_active` carries that same decision for an external
build policy (Yupana). It is its own metric, not an `effect` label on
`aegis_quiet_time_hold_active`, so existing rules on the launch-hold series do not
start matching film playback. A builds-only hold does not CPU-throttle crew panes
(`aegis_quiet_time_throttled` stays 0): the rule is "still do work, just refrain from
heavy builds", and the heavy builds are refused outright instead. A builds-only hold,
an UNKNOWN builds-only detector, and the lift of either are announced to crew panes
like any other hold.
Changing `effect` does not discard a detector's current observation.

With the default 120-second lift delay and minute probes, a continuously negative
media signal clears within 180 seconds. A message saying one reason ended does
not override another active reason or the budget governor.

```toml
[[quiet_time.detector]]
name = "gaming"
kind = "steam"
enabled = true
# Steam defaults; presence stays authoritative regardless of weak activity.
game_executable = "reaper"
game_arguments = ['SteamLaunch', 'AppId=(?P<appid>[0-9]+)']
shader_executable = "fossilize_replay"
shader_grace = 1200
# Steam launches tools and applications through the same reaper as games. An
# AppId lifts only when its type in Steam's appinfo cache is in lift_app_types or
# the AppId is in lift_appids. Every other type holds, including "application"
# and "beta" (multiplayer clients and playtests use them), as does an unreadable
# one. Defaults shown; setting a key replaces its default list.
steam_appinfo = "~/.steam/steam/appcache/appinfo.vdf"
lift_app_types = ["tool", "config", "music", "video"]
lift_appids = ["431730"]   # Aseprite, a pixel editor typed "Application"
grace = 300
lift_delay = 120
lift_rule = "absent"

[[quiet_time.detector]]
name = "media"
kind = "http_json"
url = "http://localhost:32400/status/sessions"
items_path = "MediaContainer.Metadata"
count_path = "MediaContainer.size"
match = { "Player.machineIdentifier" = "replace-with-this-desktops-client-id" }
state_path = "Player.state"
active_values = ["playing", "buffering"]
auth_header = "X-Plex-Token"
token_file = "~/.config/player/plex.ini"
token_ini_section = "web"
token_ini_key = "myplexaccesstoken"
timeout = 5
enter_delay = 0
grace = 0
lift_delay = 120
lift_rule = "inactive"
effect = "no-heavy-builds"   # playback needs CPU, not an idle fleet
```

The HTTP reader issues a bounded read-only GET, refuses redirects, and matches
only the configured client. Match values are exact strings; dotted paths traverse
JSON objects. A matching paused session is inactive. A valid zero session count
is clear; a missing schema, count/list disagreement, authentication failure or
unavailable server is UNKNOWN. State files and diagnostics never retain tokens,
URLs, response bodies or media titles. `token_file` can instead hold a plain token
when both INI options are omitted. Keep credentials outside TOML.

For another application, use a process detector without changing Python:

```toml
[[quiet_time.detector]]
name = "presentation"
kind = "process"
executable = "PresentationApp"
arguments = ['--present=.*']
min_cpu_percent = 2
enter_delay = 60
grace = 120
lift_delay = 60
lift_rule = "inactive"
```

Executable regexes full-match the basename of argv[0]; argument regexes full-match
successive argv tokens. Shell commands mentioning a signature do not qualify.
With no activity thresholds, presence is sufficient. Optional `min_cpu_percent`
uses the matched process trees and `min_gpu_percent` uses host GPU utilization;
GPU activity alone cannot attribute work to a particular process. `activity_rule`
can be `any` (default) or `all`. Missing required telemetry is UNKNOWN, including
the first CPU sample. `enter_delay` requires continuous positive observations;
`grace` is the minimum hold duration after activation. `lift_delay` requires
continuous negative observations after grace. `lift_rule = "absent"` keeps an
already active hold while the matched process/session remains present, even if
inactive. Steam requires `absent` and zero entry delay; its bounded shader phase
and AppId launch grace retain their existing semantics.

`st fleet hold <name> --set` creates a persistent manual hold for that configured
detector; `--clear` removes only that manual marker. A bare `st fleet hold <name>`
(or `all`, or `status`) only reads status, like `--status`: before aegis-e5r1 a bare
name SET a hold, and a status check run that way held the fleet for 9.5 hours. `--disable-detection` suppresses its
automatic observations without clearing manual holds; `--enable-detection`
removes that runtime suppression. An explicit `enabled = false` in TOML still
wins. Without a gaming config entry, the legacy opt-in marker remains in use.
`all` is reserved for status/probe and cannot create or clear manual holds.
Config changes invalidate cached generic observations until the next probe.
Evidence older than 180 seconds becomes UNKNOWN and fails open; manual holds do
not expire. Test real playing, paused and other-client cases before relying on a
new detector, and verify at least one run from the installed timer path.

## Account governors across hosts

With `[host.peers.*]` configured, `crew --governor`, `go`, `new`, and `tend`
use account observations from every host. `crew --governor --json --local`
exports only this host's portable policy, producer timestamps, hysteresis and
live agents; it never follows peers or exports reader credentials. The default
JSON reply has `scope: "fleet"`, merged counts, policy hosts and per-window
observation provenance. Human output names each live agent's host.

The freshest producer timestamp wins **per window**, with a deterministic host
name tie-break. Receipt over SSH does not refresh usage. A transport failure or HTTP 200 body stall
may use its last complete cached measurement for at most 15 minutes (or a
stricter configured `max_age_seconds`), labelled `stale-but-usable` in
`crew --governor` and controller output. Both the original successful timestamp
and the reported cache age constrain this grace. The existing HTTP 401 rotation
grace remains bounded by cache age at 600 seconds and the configured age limit.
HTTP 429, other HTTP errors, unknown or mixed failure status, missing age evidence,
and older caches remain signal-lost;
`on_signal_lost = "freeze"` stops new dispatch. The probe still reports failure and never parses partial bodies. Hosts without a local policy inherit the peer
policy. Multiple declarations for the same provider must agree; disagreement
holds new launches and dispatch until the policies are reconciled. The strictest
remembered window hold survives until the ordinary relaxation rules release it.

Account usage is account-scoped; an unreachable peer makes its **occupancy**
unknown, and an unreachable peer is never by itself a refusal: `st` works on any
host without another host running `st`. A peer is unreachable when SSH fails,
times out, or its `st` exits non-zero. A peer that answers with an invalid census
(unparseable, version skew, or stamped more than 60 seconds old) is treated the
same way. Any host counts such a peer as occupying exactly what its last good
census reported while that census is younger than `[host] peer_census_max_age`
(seconds, default 21600 = 6 hours). An older census, one stamped more than
60 seconds in the future, a corrupt cache, or no census at all is **advisory only**:
reported, counted as 0, never a source of policy, so it can never hold this host's launches; local capacity and
the local governor still apply. Each command prints at most one short `peers:`
line on stderr; `st crew --governor` lists every detail, and JSON includes
`warnings`, marks estimated agent rows, and the degraded admission line
marks advisory peers. Estimates count toward admission caps, but do not prove a live
session exists to refresh session-derived usage. A lane that only an unreachable
peer declared keeps that peer's last policy while its census is within the bound,
so its `max_agents` still binds; its readings keep their original age and fall to
`on_signal_lost` like any stale reading.

Cached usage readings and holds are never reused as fresh evidence. A REACHABLE
peer whose valid census disagrees on policy, membership or owner still holds launches and dispatch. A disagreement remembered only in an
unreachable peer's cache is reported as a warning. Caches live under
`governor/peers/` and are tied to the declared peer endpoint. Existing agents
keep running. Each peer call has a 20-second deadline and peers are queried
concurrently. A received census older than 60 seconds or more than 60 seconds in
the future is rejected: the clock-skew allowance is symmetric (inclusive ±60s).
Usage observations and the cache's future-stamp guard share that same
60-second future allowance.
The six-hour bound is not a minimum grace: a never-seen peer's first invalid
census is advisory immediately, and a local clock rollback greater than 60 seconds
can make a saved census future-stamped and advisory immediately. Neither path
invents zero occupancy as known fact; the warning says UNKNOWN/counting 0.
Keep host clocks synchronized.

All hosts should declare the same set of uniquely named peers; differing
membership reported by a reachable peer holds admission. `[host] admission_owner`
is optional. When it names a reachable host, launch admission is serialized on
that host using an SSH-held file lock under its governor state directory, the
census is read after acquiring the lock, and the lock remains held through
launch. `tend` recounts local agents between respawns, so one pass cannot reuse
a slot. A BUSY owner (another launch holds its lock) still refuses; retry.
The owner's helper may print login noise before its ready line, and a helper
still waiting on the owner's lock gets up to 12 more seconds to report BUSY, so
a slow SSH connection to a busy owner is never mistaken for an unreachable one.

When the owner is unreachable, or none is configured, the launching host takes
its own lock and admits against fresh censuses of reachable peers plus the last
census of each unreachable one. Real policy still refuses: FULL STOP, a frozen
account, the account cap, and a gaming hold (unless `--despite-hold`). Every
launch admitted without a fresh census of every host prints one line, for example
`admission: rig-a unreachable; admitted locally against rig-a's last census (age
14h, 3 live)`. While the owner is unreachable, `st fleet tend` on the launching
host also runs the fleet-wide sweeps the owner normally runs.

Degraded admission trades the single lock for availability. Two hosts admitting
at the same moment without a common lock can each miss the other's newest launch,
so the cap can be exceeded by at most one launch per concurrently admitting host,
and only while the owner is unreachable or unconfigured. Every count is otherwise
conservative: an unreachable peer is charged its last observed occupancy, never
less. The remote lock needs `python3` and POSIX file locking on the SSH host.

The local governor JSON includes `admission_owner`. A reachable peer whose value
is missing or disagrees holds growth, including when it runs an older binary. To
change the owner, configure the same value (or none) on every host.

This coordinates the configured `st` launch paths in a connected fleet. It is not
a distributed consensus or fencing service: out-of-band launches or loss of the SSH lock connection during a launch can defeat
serialization. Do not claim a hard quota boundary under those conditions.

## Configured pace in the Creel advisory

The headless Creel controller receives each lane's `[[governor.pace]]` rows
alongside its usage evidence. A ratio of `1.5` sets the trajectory to 1.5 times
linear usage, capped at 100%; an optional window length is carried unchanged.
Unconfigured windows retain Creel's declared trajectory. Admission caps and drain
thresholds are unchanged. Both `st crew --governor` and `st fleet tend` use this
same target. If the configured Creel probe predates this contract, the adapter
reports the advisory unavailable rather than displaying an outdated target.

## Spending envelope (`curve`)

A `[[governor.pace]]` row may declare a `curve` instead of a `ratio`: points of
`[elapsed_pct, max_used_pct]`, linearly interpolated, starting at elapsed 0 and
ending at 100, with used never decreasing.

```toml
[[governor.pace]]
window = "seven_day"
curve  = [[0, 20], [14, 40], [43, 65], [71, 80], [86, 90], [100, 100]]
```

The window is on pace while its used percentage is at or under the envelope at
the current elapsed. This expresses a front-loaded burst (20% allowed
immediately, 40% by the end of day one) with a reserve kept for the final
days (80% by day five, 90% by day six), which no single ratio can. The gate,
the utilization line and `st_governor_pace_bound` read the envelope's ratio form
`curve(e)/e`; the line names the envelope itself, e.g.
`seven_day 86%used/66%elapsed =1.31x vs 77% envelope`. Creel receives the bound
at the current elapsed, and its advisory is unavailable when that cannot be
stated. A row declaring both `ratio` and `curve` is refused. Drains are
unchanged.
