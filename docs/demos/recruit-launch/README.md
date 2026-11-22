# Signed controller launch bridge

The same library availability probe compares base
`dd142e855935d6d139a5488895b0d0551b96c3fd` with implementation
`4803a2a83e13a1244cfd2eba540cfbe46382473f`. The base has no signed launch
bridge. The candidate's default activation gate refuses before touching durable
state. An explicitly enabled **synthetic controller fixture** then enters the
existing spawn transaction, observes its ledger and card before one fixture
launcher callback, and records the matching live ledger. Reopening the SQLite
store and replaying the signed request refuses without another callback.

Watch the `SYNTHETIC` label: the printed `spawned` line comes from the real
spawn function, but its native launcher is replaced by a fixture. No pane,
protected UID, sudo helper, listener or service is started. Enrollment,
controller identity, forge/custody and capability are synthetic; signatures,
SQLite state, planner, ledger and card writes are real. The fixture models only
mutable outer test-directory ancestry. This demonstrates candidate source,
not production event-to-review acceptance or runtime activation.

Run from a checkout with the test dependencies installed:

```sh
python3 docs/demos/recruit-launch/run.py
```

The [recording output](output.log) and [timing](timing.log) are a replayable
terminal recording, not a video or an inline player. Playback was checked:

```sh
scriptreplay --log-out docs/demos/recruit-launch/output.log \
  --log-timing docs/demos/recruit-launch/timing.log
```

The small sanitized recording is retained in this repository with the demo.
The readable transcript is also the fallback for readers without scriptreplay.
Production activation remains a separate deployment decision; this adds no
transport wiring or CLI switch.
