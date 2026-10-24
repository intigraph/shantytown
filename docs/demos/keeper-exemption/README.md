# Keeper class-exemption regression

The same unlabeled Claude-lane fixture is evaluated on base `0f73ae6` and the
candidate commit linked in the PR description. The recording's candidate source
is the `work_class.py` in the commit introducing this recording.

Before: even a keeper explicitly listed in `class_exempt` is filtered.
After: that keeper is admitted. A listed worker and an unlisted keeper remain
filtered on both revisions. This is a library fixture, not live dispatch or a
configuration change. The regression test also exercises floor, freeze and drain.

[Output](output.log) · [Timing](timing.log) · [Probe](probe.py)

Repeat from repository root:

```sh
PYTHONPATH=. python3 docs/demos/keeper-exemption/probe.py 0f73ae6
```

Download both logs into one directory and replay with:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

Small sanitized logs are retained here with the reproducer.
