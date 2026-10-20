# Prepared package migration

Trigger: a fresh card has created an empty shared package directory before a
stopped legacy card migrates. The same fixture refuses on base and succeeds on
the candidate, preserving the native lock inode and retaining the original.
Process custody and filesystem detection are explicitly mocked; this does not
prove a live migration, runtime health, or reclaimed capacity.

[Recording](output.txt) · [Timing](timing.txt) · [Reproducer](demo.py)

Base: `bb9f8d2a4503c0b4b9c1721185f52316e5ccfc6a`. The recording prints the
candidate implementation SHA256, which can be compared to the reviewed file.
Small output/timing artifacts are retained here with the probe.

```sh
python3 docs/probes/prepared-package-migration/demo.py
scriptreplay --log-out docs/probes/prepared-package-migration/output.txt --log-timing docs/probes/prepared-package-migration/timing.txt
```

The recording requires downloading and a terminal replay tool; no inline player
is assumed. The readable output is the fallback.
