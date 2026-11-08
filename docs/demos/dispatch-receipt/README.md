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
