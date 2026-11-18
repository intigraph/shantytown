# Duty CLI boundary: source-only recording

A synthetic stopped worker holds an external queue duty. The same actual CLI
handler runs against base `135c3374901acda2c0e0002a9d80e77f4bfb6a0c`
and this proposal's combined source. The PR body pins the published head.
The fixture replaces pane and tracker boundaries; no live agent is stopped.

Watch `stop_callback_called`: base reaches the stop callback without disposition
(exit 0); candidate refuses before it (exit 1). The candidate also recognizes
`--repool-work`. Separate regression controls prove explicit repool creates and
notifies the repair before stopping, UNKNOWN refuses, internal cycles retain
ownership, and administrator anchors render fresh/stale duty census correctly.

The actual output-only terminal recording is [output.log](output.log), with
[timing.log](timing.log). Download both and replay:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

To reproduce, check out the base and candidate separately, then run:

```sh
DEMO_BASE_SOURCE=/path/to/base DEMO_HEAD_SOURCE=/path/to/candidate python3 probe.py
```

The source checkouts need the repository's test dependencies. The probe imports
their respective CLI and existing synthetic fixtures in separate processes.
These source observations do not establish installed inventory, live stop or
handoff acceptance, serving metrics, or rollout authorization.
