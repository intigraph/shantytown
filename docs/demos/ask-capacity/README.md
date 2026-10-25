# Human decisions and work capacity

With five ordinary work records and five owned ASK records, a new P1 was refused
because the work count was ten. The candidate counts five and admits the P1.
Ten ordinary records still refuse admission. All fixture rows, owners and statuses
remain unchanged.

This is an isolated library fixture, not an installed-service result. The same
probe ran against base `cd2e749fd723959e40049e00c32692cd042ded33` and code head
`63058c9ee3c64ff29c2f67e6f91d3bea01010976`.

From either checkout, run `PYTHONPATH=. python3 docs/demos/ask-capacity/probe.py`
(copy this probe into the base checkout first). The [transcript](demo.txt) and
[terminal recording](demo.cast) preserve actual output and elapsed timing.
Download the recording and run `asciinema play demo.cast`; inline playback is
not provided. These small artifacts remain in Git with the change.

Tests separately cover no-deferral behavior, unknown and external blockers,
ASK-to-work conversion and fresh admission despite a cached display snapshot.

## Malformed-label repair

The [second recording](malformed.cast) and [transcript](malformed.txt) run the
same [probe](malformed-probe.py) on pre-repair head
`5a000cc04d894d5ef05afe8d06558a2b2c445cc6` and repaired code head
`71e89f4fa761c234d72a2d193afd34991a0a29dd`.
Ten ordinary rows carrying the malformed top-level map `{"desk": false}`
previously counted zero and admitted a P1; the repair counts ten and refuses.
A malformed candidate on an already full plate also changes from allowed to
refused. Supported ASK labels, title and human blockers retain their existing
behavior; the affected suite includes no-deferral positives.

Repeat with `PYTHONPATH=. python3 docs/demos/ask-capacity/malformed-probe.py`
from either source checkout (copy the probe into the old checkout first).
These are isolated read-only library fixtures, not production tracker calls.
Download the cast and use `asciinema play malformed.cast`; no inline player is
claimed. The later demo-only commit preserves the demonstrated code.
