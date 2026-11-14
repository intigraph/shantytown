# Haul CI wait policy: before and after

The same private fixtures exercise the actual haul message functions and the
Dispatcher used by `st work defer`. They create no live tracker records.

Before this change, 20 cases failed: both messages lacked the instruction to
stay in progress, and CI/merge/review waits could be deferred with a 25-hour
backstop, including P0 work and `--window` requests.

After this change, the same 20 cases pass; additional controls cover old no-op records and an appointment disguise. A broader affected run passed 283
tests under the HOME guard (163 watched paths and five UID resources clean).

Reproduce:

```sh
python3 -m pytest -q tests/test_haul_wait_policy.py
```

The refusal says to stay `in_progress` and record the exact wake. No tracker
bytes change. Existing non-CI deferrals and historical CI event readers remain
covered by the adjacent tests. This is source behavior proof, not an installed
runtime or new capacity-hold lifecycle claim.

The first full-suite run reported 10,383 passed, 33 skipped and ten failures
in the superseded CI-deferral policy/haul-wording tests. Those expectations
were updated while keeping explicit scheduled appointments and historical
readers covered. The final affected run is the qualification for that correction;
the full hosted matrix remains required before review/landing.

## Actual before/after recording

The [output transcript](output.log) and [timing data](timing.log) record the
same P0 exact-head CI defer request against base
`4b422d9e7d986dd5c87475b058bffad1ed0a5f0a` and the candidate source in this PR.
The baseline stores `deferred` and its resume prompt recommends defer; the
candidate refuses with the item still `in_progress`. An explicit scheduled
review appointment remains a positive control on both revisions.

Replay after downloading both files:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

This is a replayable terminal recording, not an inline video. To repeat against
an isolated checkout, set `PYTHONPATH` to that checkout and run
`reproduce.py` from outside it. Add `--expect-deferred` only for the baseline.
The reproducer uses private FilesTracker records, no live board or scheduler.
The PR body names the exact demonstrated candidate commit. Small plain-text
assets are retained in this existing docs/probes location.
