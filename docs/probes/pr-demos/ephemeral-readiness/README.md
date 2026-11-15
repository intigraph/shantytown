# Stop capacity respects unattended UID readiness

The terminal recording compares baseline `2ff8a6115a9c61f33b404a14d258fe962b2c28ee`
with this proposal's `stop_policy.ephemeral_free_slots`. Both use the same private
fixture: an unattended administrator, two nominal slots, and unassigned P0 work.
No agent, account, privileged helper or installed configuration is changed.

With UID readiness false, watch `slots=2 block=True` become `slots=0 block=False`.
The readiness-true control preserves `slots=2 block=True`. Explicit attended
postures and occupied slots are covered separately by the regression tests.

Replay the recorded terminal output with:

```sh
scriptreplay --log-timing demo.timing --log-out demo.log
```

Or read [the transcript](demo.log). To repeat the comparison from the repository
root, run `PYTHONPATH=. python3 docs/probes/pr-demos/ephemeral-readiness/demo.py`.
The reproducer extracts only the baseline and candidate function definitions;
the decision engine and fixture are shared. This demonstrates source behavior,
not installed adoption or proof of OS user isolation.

The small recording, timing and reproducer stay with the source revision for
review and reproducibility; they contain no private host or credential data.
