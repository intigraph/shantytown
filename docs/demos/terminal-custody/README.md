# Terminal custody before and after

The same disposable fixtures call the real `delivery.supervise` on main
`e126d6d61415d3f8cf386caf6ff69ba37ec28d4b` and this branch's delivery module.
Session IDs, screen frames and inbox storage are synthetic. No live pane,
production inbox, custody record or service is touched.

Watch four old-session bodies change from four notices and retained queued
custody to one consolidated notice and terminal orphaned custody. A drained
queue becomes dequeued, while its unread notice keeps the backlog watch present.
The busy-queue control stays queued. A previously alerted watch clears only in
the fixture with no unread notices and no remaining live custody. Every case
asserts that zero terminal keys were sent.

Run `python3 docs/demos/terminal-custody/demo.py` from the repository checkout.
The recording prints both the exact baseline revision and candidate module
SHA-256. [Output](output.log) and [timing](timing.log) are a small sanitized
terminal recording retained in the existing repository demo destination.
Download both and replay with:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

Playback requires util-linux; this is a terminal recording, not an inline video.
The fixture demonstrates source behavior, not installed/runtime acceptance.
Live stale-record counts and natural watch rearming remain separate checks.
