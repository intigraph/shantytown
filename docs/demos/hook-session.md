# Native hook session in lifecycle writes

An isolated stats hook receives `native-fixture-session` with no session environment.
Base `7510e04d678235a4b3b56bdf7faa907cf49feb1c` omits the HTTP session;
candidate `5369ceb5dc8b8f7e1cd7359769a21651da4a8622` carries the native session.
Both leave the session absent outside publication. The publisher is intercepted
and reads the real header helper; no HTTP request or production credential is used.
This demonstrates source behavior, not installed adoption or alert recovery.

The small output-only recording and timing file are retained here with the source.
Playback was verified with `scriptreplay`; download both files to replay:

```sh
scriptreplay --log-out hook-session.log --log-timing hook-session.timing
```

- [Recording output and readable transcript](hook-session.log)
- [Recording timing](hook-session.timing)
- [Repeatable reproducer](hook-session.py): run `PYTHONPATH=. python3 docs/demos/hook-session.py`
  from the repository root, retaining the named base commit locally.

The three regression cases fail on base and pass on candidate; focused tests also
cover restoration after publication failure, nested scopes and thread isolation.
