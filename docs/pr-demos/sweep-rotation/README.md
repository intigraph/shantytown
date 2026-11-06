# Bounded tend sweep rotation

A simulated 130-second inbox sweep consumes the unchanged 120-second admission
budget on four real `_tend_once` calls. Watch cumulative deferral executions:
base `[0, 0, 0, 0]` becomes candidate `[0, 1, 1, 2]`. Respawn-first is asserted
on every call. Baseline test failure is intentional and checked by the driver.

Base: `0489a18d5e7ad914d1d0339e1e7dca7248b626b9`. Candidate is the source
containing this demonstration, with the two runtime SHA-256 hashes printed in
the [recording](output.log). The exact-head commit is also stated in the PR.
The driver archives base into two disposable directories and overlays the
candidate runtime files in one. Both receive the identical new regression
probe, adding only an observation print that bypasses pytest capture.

Repeat from the repository root with Python 3.14 and pytest installed:

```sh
python3 docs/pr-demos/sweep-rotation/demo.py
```

Download [output.log](output.log) and [timing.log](timing.log), then replay:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

This is a replayable terminal recording and readable transcript, not an inline
video. The small sanitized files are retained with the source under the existing
`docs/pr-demos` convention. All dependencies are isolated fixtures: no live
tracker, notification, process launch, or installed scheduler is exercised.
Production acceptance separately counts deferral-sweep executions per original
scheduled tend after normal source adoption.

The first budget-skipped label becomes the next pass's start. Earlier labels
are unobserved for that pass; after completing the suffix, the following pass
wraps to the start. A disappearing optional label resets the cursor for the next
pass. The scheduler does not interrupt an in-flight sweep, change the 120-second
budget or condition-read caps, or equate any skipped work with a successful
read. Rollback is an ordinary source revert; the old source ignores the new
scheduling-only ledger.
