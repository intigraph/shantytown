# Protected persistent nonce state and launch admission

The recorded mutation probe signs head `a…a`, then an authority callback changes
the caller envelope to head `f…f`. Base
`fd10adc776c214200f1f143f45352123c0354044` returns the unsigned changed head.
Candidate source `b78b7c565f3546006f49bf64a6b180e6d36e7182` returns the signed head by
detaching canonical signed bytes before authority callbacks.

The same recording calls the new handoff using explicit fixture identity, forge,
custody, protected-capability and governor adapters plus a real private SQLite
store and the existing planner. Watch its prepared receipt: durable nonce,
`live: false`, `execution: refused`, `activation: gated`. Reopening the store
refuses the same request, and replacing its database path with a symlink refuses.

[Recorded output](output.log) and [timing](timing.log) are retained in the
repository's existing small-demo directory. Download both for terminal playback:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

Playback was verified. The output is also a readable transcript, not an inline
video. Reproduce on Linux from the repository root with test dependencies:

```sh
python3 docs/demos/recruit-persistent/run.py
```

The recording reports hashes of the four executed candidate source files. Later
caption changes preserve them. Fixture dedicated IDs derive from the current
UID, so request and plan digests may differ on another machine.

Limits: trusted outer fixture ancestry is modeled explicitly; all created
private directories, nofollow opens, SQLite writes and replay checks are real.
Production has no fixture exception. This is a source/library demonstration,
without host enrollment, live requests, native UID drop, privileged invocation,
or a job/card/pane. Preparation is not a runtime-cap reservation or launch lease.
Merge permitted; runtime activation is gated separately.
