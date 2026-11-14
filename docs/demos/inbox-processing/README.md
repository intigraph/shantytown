# Inbox processing decisions

Synthetic files-inbox fixture, base `bfc8427ad50a` versus this change's source
files. Trigger: a producer repeats an unchanged body 34 times after ordinary
receipt ACK. Base exposes 34 eligible messages again. Candidate processing ACK
exposes zero, while all 34 durable records remain. Changed findings are a
positive control and remain eligible. DEFER becomes eligible at its deadline
for the original receipt only. No production inbox, incident or system clock
is changed; this demonstrates source behavior, not installation or fleet-wide
suppression.

Repeat from the candidate checkout, with a separate base checkout:

```sh
DEMO_BASE_ROOT=/path/to/base bash docs/demos/inbox-processing/run.sh
```

This directory retains a small **output-only terminal recording** and its timing,
plus the executable reproducer. Download both files and replay with util-linux:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

[Readable transcript](output.log) · [Timing](timing.log) · [Reproducer](probe.py)

Playback requires `scriptreplay`; inline video playback is not claimed. Retain
these small sanitized artifacts with the source PR, rather than an external
upload or a new artifact service.
