# Roster capacity observation

A crew render first reads assignments for its named roster. Previously,
capacity counts read each owner again. This change includes blocked work in
that same bounded observation and reuses it for the render's capacity counts.
Blocked work does not replace a held or ready assignment. Admission readers
outside an explicit crew render still read live.

## Native fixture recording

[Download the terminal recording](assets/roster-capacity.cast) and replay it
with `asciinema play roster-capacity.cast`. It is an asciicast v2 terminal
recording, not a browser video. The recorded output is from actual test runs.

Base: `585fceaf68a8118dacf3e5a2dcc46ed5b7ce28d3`.
Candidate code: `38018fc` (the subsequent commit only adds this recording and caption).
Target: an isolated Quipu 0.13.0 fixture with 80 work items and 13 owners.

On the base, the regression refuses the extra reads: `assert 31 == 5`.
On the candidate, the roster and all capacity counts use 5 queries together;
capacity adds 0 queries. The blocked item remains in capacity counts and is
excluded from assignment selection. A fresh reader observes deletion.

Repeat the candidate demonstration with a local native server binary:

```sh
SHANTYTOWN_TEST_QUIPU_SERVER=/path/to/quipu-server \
  python -m pytest -q -s tests/test_seeds_plate_batch_native.py
```

The base run uses the candidate regression test against the base package and
is expected to fail at the additional-query assertion. The candidate run must
pass. The recording also shows the unchanged global queue and malformed-status
controls. This proves fixture behavior and call counts, not installed latency,
live fleet completeness, or the one-hour request-rate acceptance.
