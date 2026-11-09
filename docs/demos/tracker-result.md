# Tracker failure output

A fixture returns HTTP 408 during an exact-item read. Preserved legacy mode
exits 2 with zero stdout bytes; opting into `--result-json` keeps the failure
status and reports TIMEOUT, READ and NOT_APPLICABLE, with null data.

Recorded implementation: `3d396f7a` (base `ea5608bcaedd7405c7815b708b576e0f4d8f65ae`).
This compares two modes of the recorded implementation; it does not claim an
independently executed base binary. The new option has no base equivalent.
The fixture replaces only the tracker and calls the real item dispatcher. It
performs no network request, mutation, retry or installed-harness qualification.

Reproduce from the source root:

```sh
PYTHONPATH=. python3 docs/demos/tracker-result-demo.py
```

[Output recording and readable transcript](tracker-result.output) and
[timing](tracker-result.timing) are retained in this existing demos directory.
Replay requires downloading both files and util-linux `scriptreplay`:

```sh
scriptreplay --log-out tracker-result.output --log-timing tracker-result.timing
```

Actual output and timing were recorded with util-linux `script`; playback was
verified. This is a terminal recording, without an inline video embed.
