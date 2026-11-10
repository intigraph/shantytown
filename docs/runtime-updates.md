# Runtime update replacement

`st fleet tend` observes the exact locally owned session's running harness
version and the selected installed executable's `--version`. It never installs
an update. Claude evidence comes from native transcript version metadata;
Codex evidence uses the owned daemon/thread binding and native session header.
Missing, old, foreign or prerelease evidence stays unknown.

With automatic cycling enabled, tend writes a checkpoint from the current
anchor, stored resume notes, latest agent-written item comment and named graph
references. This is explicitly a machine snapshot of written state, not a claim
to capture unwritten reasoning. An agent can still supply a richer manual
checkpoint. Existing manual requests win atomic admission.

The snapshot is posted and read back on the anchor item before the replacement
request is recorded. A failed or indeterminate checkpoint write is retained as
`checkpoint-failed`; tend does not replay it. Resolve the write failure and use
the ordinary explicit checkpoint/cycle path to rearm that generation. With a
verified empty plate, the complete snapshot lives in the durable cycle request.

The request uses the existing cycle executor with `no_in_place=true`. It cannot
clear context in place and call that a runtime update. Busy turns, nonempty
composers (including Remote Control input), background tasks and unknown shell
ownership defer replacement. The composer is never cleared or submitted by the
roller. Input refusals are recorded on the pending request, reported by the
existing cycle status/notifier and retried by later idle passes. Governor,
operator-stop, household hold, tree custody and launch admission still apply.

Credential rendering is checked before a `--self --no-in-place` request is
accepted and again before destroying the current process. It uses the existing
provisioning sources: environment, `provision/secrets.env`, and authorized
per-agent overrides. A missing variable is named with the normal remedy; no
secret value is logged and no rendered workspace token is borrowed.

The fleet rolls one agent at a time. Each peer's own tend handles its local
processes; a host never drives a foreign pane. Admission uses the configured
fleet admission owner (or the first declared host name), with a fresh peer
runtime census under that shared lock. An unreachable owner, failed peer read,
or live peer lacking runtime metadata defers new updates; this path does not
use ordinary launch capacity's degraded local admission. Update peer st first
when its runtime metadata is unavailable. A launch receipt leaves the roll
in `awaiting-version` until native metadata from a **different exact session**
proves the target running version (or a newer installed version that arrived
during deferral). The old session identity and running version remain bound;
an intervening downgrade cannot use that request. Only then can the next agent roll. Unknown
receipt or a stranded request blocks advancement rather than claiming success.

`notify/runtime-roll.json` records session, harness, running/installed versions,
phase, blocker and observation time. `st crew --json` exposes that record as
`runtime_update` per agent, including in fleet peer rows. These are timestamped
observations, not live probes made by the display. `SHANTY_AUTO_CYCLE=0` disables
automatic update requests along with context cycling; explicit requests retain
their usual behavior.

Acceptance requires a real newer install, observed idle replacement on both a
remote-controlled peer and a local agent, resume brief delivery and new-process
version receipts. Unit tests do not establish that installed acceptance.


The peer-visible requested generation is persisted before its cycle request.
A failed reservation write admits no request; an uncertain request or failed
final ledger write retains the published reservation, so another host remains
fenced until the exact new-session version receipt resolves that generation.
