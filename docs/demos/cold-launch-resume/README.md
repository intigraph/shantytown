# Observing a cold-launch receipt

The same cold-launch marker is untestable at base a2afbdf4 and testable in this proposal. This library fixture rejects an override and accepts a verified ordinary receipt. It does not launch a process or write a tracker item.

Replay the [recording](output.log) with [timing](timing.log):

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

Repeat with `python3 docs/demos/cold-launch-resume/demo.py`. Native launcher tests separately exercise admission outcomes with mocked process transport. No production cold launch, installed adoption or provider acceptance is claimed.
