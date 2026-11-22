# Protected inherited receiver demonstration

Before: main e7f9b540 has the connected-channel handler but no protected listener
accept entry. After: the new unwired library entry refuses while activation is
OFF, then accepts one signed private fixture request through the existing spawn
path. Replaying that request refuses; a wrong configured controller UID refuses
before accept. The listening socket stays open for its owner.

Protected enrollment, peer enrollment and job launch are synthetic; the Unix
listener/connection, Ed25519 signature, SQLite nonce state and native spawn
ledger are real. No live host identity, key, socket installation, service or
actual job starts. Runtime activation remains separately gated.

From the repository root with test dependencies installed:

```sh
python3 docs/demos/recruit-inherited-receiver/run.py
scriptreplay --log-out docs/demos/recruit-inherited-receiver/output.log --log-timing docs/demos/recruit-inherited-receiver/timing.log
```

The small output/timing pair is retained with the source. It is a terminal
recording requiring download and scriptreplay; inline playback is not assumed.
The PR names the exact candidate source. Test-only enrollment/launcher fixtures
are part of the reproducer and are not production enrollment instructions.
