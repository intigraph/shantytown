# Retained dispatch receipt diagnostics

A prepared receipt belongs to Ada; a later request names Ben. The same
disposable library fixture refuses the request on base `1ef8541d` and the
candidate. Watch the candidate name the retained ID, original worker, state,
revision and read-only reconcile command. Both runs preserve receipt bytes and
mtimes, with execution unauthorized. No board or pane is contacted.

The candidate recorded source SHA256s are:

- `dispatch_receipts.py`: `bdaacbcce2a801c22950eb337b1fbacdcab6ca3b218d6aaf3e3ab79f94904e6f`
- `dispatch_binding.py`: `e2649a956b07d0540cbbad0d372a51bc54951dd079a46df95c23c36b62278149`

[Recording output](output.log) and [timing](timing.log) are retained here as small
repository artifacts. Download both and replay with util-linux:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

Playback was checked. Recorder metadata was sanitized; observed output and timing
are retained. This is a terminal recording, with no inline video player. To
repeat the probe from either source checkout:

```sh
PYTHONPATH=. python3 docs/demos/dispatch-scope/probe.py
```

The binding integration tests separately exercise a real Dispatcher and file
tracker, execute the printed original-worker CLI reconcile command read-only,
and check native ownership/defer/read-failure controls for the supersede hint.
This library recording does not prove installed or live dispatcher acceptance.
