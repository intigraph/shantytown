# Bound dispatch receipt demonstration

The same stale item echo incorrectly assigned work on the base; the candidate
retains a pending receipt and leaves work unassigned. A confirmed exact-body
submission assigns once. Repeating it sends twice on the base, but reuses the
same receipt with one send on the candidate. Read-only reconciliation changes
neither file bytes nor modification times.

This is an isolated library fixture using the actual `Dispatcher`, file tracker
and receipt coordinator, with a substituted terminal. It does not demonstrate
a live harness, native Seeds service, installation, or natural arrival.

Base: `9b08512c078632eb54406fd1d6027aeb9f800fc1`.
Candidate behavior: `b5dca181ded5ccd623b26c16aba8d724fb10f464`.

Download [output.log](output.log) and [timing.log](timing.log), then replay:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

The output log is also the readable transcript. Playback requires a terminal
and util-linux `scriptreplay`; no inline player is assumed. These small sanitized
artifacts are retained here with the reproducer for the life of this change.

To reproduce, extract the base source into a separate directory, set `DEMO_BASE`
to that directory and `DEMO_CANDIDATE` to the candidate checkout, then run
`bash docs/demos/dispatch-receipt/run.sh` with the project's dependencies
available. Both runs execute the same [probe.py](probe.py). On installations
requiring a HOME escape guard, wrap that command with the normal guard.


## Transport custody recovery repair

On source parent `0d23416cbe16329a17e0a9d40104abe00454d2e8`, an actual
`Tmux.send` returning `None` wrote terminal custody state `delivered`; a second
`Dispatcher.go` assigned and authorized the worker despite no submission
observation. The repair requires durable positive exact-body/pane evidence
and the same runtime identity before and after the transport call. Legacy
`delivered` records alone cannot authorize recovery.

The [paired recording](custody-output.log) and [timing](custody-timing.log)
show the same negative input and positive interrupted-coordinator control on
both source versions. The negative now remains unassigned and unauthorized;
the genuinely observed positive still recovers. Both use one send. This uses
the actual transport wrapper, dispatcher, file tracker and receipt coordinator;
only `_send` and runtime discovery are substituted. It proves source behavior,
not installation or a natural harness arrival.

Replay with `scriptreplay --log-out custody-output.log --log-timing custody-timing.log`.
Repeat the [probe](custody_probe.py) against an extracted source using
`python3 custody_probe.py --source SOURCE --expect before` for the parent or
`--expect after` for the repaired revision containing this recording. Pytest
is needed for the shared isolated fixture. These artifacts use the same
repository retention policy as the original demonstration.
