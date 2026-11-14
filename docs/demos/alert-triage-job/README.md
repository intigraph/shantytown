# Frozen alert-triage input demo

Run from the source root:
`PYTHONPATH=. python3 docs/demos/alert-triage-job/reproduce.py`.

The new compiler did not exist on base `45024ac8`. This synthetic source
example shows its added behavior: one pinned fingerprint and original item
become ordinary per-slot launch bindings with a definition/input/prompt digest
receipt. Changing that input after pinning refuses before creating output.
All allocations and executable paths are synthetic; runtime admission stays
false. No Alertmanager read, enrollment or native execution is demonstrated.

The [terminal recording](output.log) and [timing](timing.log) replay with
`scriptreplay --log-out output.log --log-timing timing.log` after downloading
both files. The [transcript](transcript.txt) is the readable fallback. Replay
was checked; no inline video playback is claimed. Recorded module bytes are
from `99d79252`; the following commit adds only this caption and recording.
These small sanitized fixtures remain in the repository with its demo docs.
The focused renderer integration and negative controls are in
`tests/test_alert_triage_job.py`.
