# Bounded inbox acknowledgment

The same synthetic 96-message inbox and 1.2-second hard deadline run against
base c2200662533bdc277f0be4b46def0787acadb637 and this change. The real CLI and
TrackerInbox run with a synthetic tracker taking 30ms per close; this does not
measure remote service latency. A three-message base control confirms output
works when the batch completes.

Before: the process is killed after independent closes persist, with no payload
or progress output. After: the command completes one 15-message batch, flushes
all consumed payloads, and reports 81 snapshot messages not attempted. Tests
also kill the process during a close to check buffered-pipe output survives.

Reproduce from the repository root: `sh docs/demos/inbox-read/run.sh`.
The recording demonstrates the proposal containing these artifacts. Retain the
small recording and readable output with the code for reproducibility.

[Recorded output](output.log) and [timing](timing.log) form a terminal recording,
not a video. Download both and replay with:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

Playback requires util-linux scriptreplay; no inline player is promised.
