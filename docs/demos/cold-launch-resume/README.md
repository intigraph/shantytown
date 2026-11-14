# Observing a cold-launch receipt

The same cold-launch marker is untestable at base a2afbdf4 and testable in this proposal. This library fixture rejects an override and accepts a verified ordinary receipt. It does not launch a process or write a tracker item.

Replay the [recording](output.log) with [timing](timing.log):

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

Repeat with `python3 docs/demos/cold-launch-resume/demo.py`. Native launcher tests separately exercise admission outcomes with mocked process transport. No production cold launch, installed adoption or provider acceptance is claimed.

## Assigned harness and bare bindings

The [assigned-harness recording](assigned-output.log), with
[timing](assigned-timing.log), compares base `2016b460` with this source proposal.
The same assigned-Claude fixture changes from refused to recorded; the bare
agent binding changes from refused to true after a later verified launch.
A context-clear/cycle observation remains false. No process is launched.

Replay with `scriptreplay --log-out assigned-output.log --log-timing assigned-timing.log`
or repeat `python3 docs/demos/cold-launch-resume/assigned-harness.py` from the
repository root. This demonstrates source behavior, not installed acceptance.
