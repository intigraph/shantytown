# Spec-notice observation demo

Private source fixture, base `eafa6b46d151aa4338f555eabd1f8d5c3b9a160e`
and implementation `14a1bbe59feb600644274fb1f09c0e314ae2e255`.

The same generated spec notice remains deduplicated on both revisions. Base has
no observation reader. The candidate reports EMITTED with arrival UNKNOWN until
the exact notice appears in a session-bound native input fixture. The wrong-session
control remains UNKNOWN; the accepted input reports HARNESS_OBSERVED; replay leaves
one receipt. The fixture does not prove installed or live harness behavior.

[Output recording and readable transcript](spec-observation.log) ·
[Timing](spec-observation.timing) · [Reproducer](spec-observation.py).
These small sanitized artifacts use this repository's existing demo directory and
are retained with the source. The recording is a terminal log, not an inline video.

Download both log files, then replay with util-linux:

```sh
scriptreplay --log-out spec-observation.log --log-timing spec-observation.timing
```

Repeat against a checkout of either revision using the candidate's reproducer:

```sh
PYTHONPATH=/path/to/revision python3 docs/demos/spec-observation.py
```

All writes target disposable local fixtures. No live generation, sender, owner ACK,
runtime configuration inspection or deployment occurs.
