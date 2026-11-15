# Preserve a live replacement when startup is unverified

The same isolated launch result (`CANNOT_TELL`) and live screen enter the second
restart admission at base `c96be285`, but remain UNKNOWN without another restart
in this proposal. A nonlive control retains the existing fallback admission.
The fixture refuses that fallback before any stop; no process is launched.

Repeat `python3 docs/demos/live-startup-cycle/demo.py` from the repository root.
Replay the [recording](output.log) with [timing](timing.log):

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

This demonstrates source behavior, not installed adoption or real handoff speed.
Natural before/after handoff timing remains a separate acceptance check.
