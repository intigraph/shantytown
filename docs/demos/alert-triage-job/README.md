# Frozen alert-triage input demo

Run from the source root:
`PYTHONPATH=. python3 docs/demos/alert-triage-job/reproduce.py`.

The new compiler did not exist on base `45024ac8`. This synthetic source
example shows its added behavior: one pinned fingerprint and original item
become ordinary per-slot launch bindings with a definition/input/prompt digest
receipt. Changing that input after pinning refuses before creating output.
All allocations and executable paths are synthetic; runtime admission stays
false. No Alertmanager read, enrollment or native execution is demonstrated.

The retained [transcript](transcript.txt) is actual reproducer output, not a
video or installed acceptance recording. The focused renderer integration and
negative controls are in `tests/test_alert_triage_job.py`.
