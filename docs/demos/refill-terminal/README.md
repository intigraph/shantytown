# Terminal custody reservation release

This isolated library probe starts with an ended composer and recorded durable
pointer. The existing delivered-input reconciler refuses terminal custody.
The new path refuses when a live owner holds the item, then releases the exact
lane-bearing reservation when the native tracker fixture is unassigned. Watch
that the custody bytes remain unchanged and delivery remains UNKNOWN.

[Actual transcript](transcript.txt), retained alongside [the probe](probe.py).
This is a text transcript, not a video: asciinema is unavailable on the authoring
host. No production tracker, process, message or reservation is used.

Reproduce from the repository root with the declared test extras installed:

```sh
python3 docs/demos/refill-terminal/probe.py
```

Base: `2016b460badce9ad5630af91c302ddd485f45b42` delivered-input reconciler.
Candidate module SHA256:
`137c84c90a775328a5c162c5950137594ef79fb3adff5bc26fea898993f53fe1`.
The containing PR commit pins the probe, candidate and transcript together.
This demonstrates source behavior with fixture ownership; it does not establish
installed or runtime acceptance. The normal source rollback retains the audit
and never recreates a released reservation or resends its message.
