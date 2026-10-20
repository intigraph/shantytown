# Push deadline demonstration

A validation hook needs longer than one minute. The old default reports the
publication as indeterminate at 60 seconds; the new default lets the hook finish.
Explicit short deadlines still report indeterminate and require remote read-back.

Base: `281100288e7a196afcf88e37ab342880ed02afea`.
Demonstrated implementation: `75373d1e29a4165fd334fc87df3161d3bcbdf47d`.
Subsequent recording/caption commits preserve these implementation bytes.

## Replayable terminal recording

[Output and readable transcript](push-timeout.log) and [timing](push-timeout.timing)
are small, retained Git artifacts in the existing demo directory. They are a
terminal recording, not a video or an inline player. Download both and replay:

```sh
scriptreplay --log-out push-timeout.log --log-timing push-timeout.timing
```

The recording calls the actual base/head push runner with a **modeled 121-second
command**: the injected subprocess raises a timeout when its budget is too short.
It contacts no remote. Watch the default change from rc124 to rc0, while the
explicit one-second negative control stays rc124. This demonstrates deadline and
refusal behavior, not a real 121-second Git operation.

Repeat with [the reproducer](push-timeout-demo.py), selecting each checkout:

```sh
PYTHONPATH=/path/to/base python3 docs/demos/push-timeout-demo.py
PYTHONPATH=/path/to/head python3 docs/demos/push-timeout-demo.py
```

## Separate real-hook measurement

The same private local Git source/bare-peer fixture, with an actual `sleep 61`
pre-push hook and no timeout override, measured these selected output fields:

| Source | Default | Elapsed | Push rc | INDETERMINATE | Destination present |
| --- | ---: | ---: | ---: | --- | --- |
| Base | 60s | 60.060s | 124 | true | false |
| Candidate | 600s | 61.012s | 0 | false | true |

These are source-checkout measurements, not an installed CLI or production
publication. The focused test `test_default_timeout_allows_real_slow_hook`
additionally runs a real 61-second hook through the CLI against two local peers.
Explicit deadline, hook refusal, invalid deadline, and timeout-after-commit
controls remain in `tests/test_push_every_remote.py`. The real fixture and
recording ran under a HOME/resource guard; no production push was used.
