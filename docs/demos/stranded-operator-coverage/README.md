# Recorded operator-stop work coverage

This output-only terminal recording runs the same isolated source-library fixture
against base `0fb0cdc09135ee7492b2565cd1330bf89b58fc77` and the candidate containing
product commit `f7ae4d3c`. The subsequent current-main merge changes the display CLI,
not these supervisor modules. The recording and reproducer are retained here with
the PR, following the existing repository demo convention.

Input: 300 deferred ASK work items and 241 inbox pointers, a recorded operator
stop, and explicit process evidence. The old ranking reader exposes no parked
items. Watch work coverage and release-due change from 0 to 300; the live-process
control stays at zero. Inbox recipients are retained. This uses observe mode,
private temporary files and synthetic registry/process/inbox boundaries: it
proves source behavior, not installed acceptance or a production unassignment.

Reproduce from a fetched checkout with the base commit available:

```sh
python3 docs/demos/stranded-operator-coverage/run.py
```

[Readable transcript](transcript.txt) and [timing](timing.txt) form a replayable
util-linux terminal recording. Download both and replay with:

```sh
scriptreplay --log-out transcript.txt --log-timing timing.txt
```

Playback was checked locally; no inline browser player is claimed. The assertions
also check the before/after/control counts. Actual scheduled acceptance still
requires the reviewed installed supervisor and separately admitted managed mode.
