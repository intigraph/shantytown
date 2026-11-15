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

## Ordinary bounded-read starvation repair

Trigger: 34 retained processing-ACK duplicates precede one changed critical
finding. [Output-only recording/transcript](starvation-output.log) and
[timing](starvation-timing.log) compare base `e46e8cfd31f73735e89c0fc0eaf205d2951a9607`
with repair source `3c589b99` (later recording-only commits do not change that
code). Base ordinary CLI read returns success but acknowledges zero and never
presents the changed finding. Candidate presents and acknowledges that finding;
both retain all 34 suppressed original records. This is a synthetic source
fixture, not installed acceptance or a live alert replay.

Repeat from this checkout with an isolated base checkout:

```sh
DEMO_BASE_ROOT=/path/to/e46e8cfd sh docs/demos/inbox-processing/starvation-run.sh
scriptreplay --log-out starvation-output.log --log-timing starvation-timing.log
```

The replay command runs from this demo directory. Its terminal playback was
checked; inline video is not claimed. The native-window tests separately show
bounded expansion and UNKNOWN/no ACK at the 100-row scan cap. The files fixture
already loads its local mailbox and therefore does not demonstrate remote read
cost. Retain the small sanitized recording with this PR.
