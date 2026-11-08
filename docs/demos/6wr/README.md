# Idle Codex queue replay

The same synthetic pane and durable inbox body pass through real custody
supervision in base `20555332` and the candidate source. The base incorrectly
marks custody `dequeued`, with zero lead events. The candidate retains `queued`
and persists one lead event immediately. Both keep the unread pointer and send
zero keystrokes. Fake panes and a temporary local inbox isolate the demo from
installed services; this does not demonstrate live delivery or a runtime fix.

[Output recording](output.log) and [timing](timing.log) are retained here as a
small repository artifact. Download both and replay with
`scriptreplay --log-out output.log --log-timing timing.log` (terminal replay,
not an inline video). The output is also the readable transcript. Reproduce with
`python3 docs/demos/6wr/reproduce.py <source-checkout>`; pytest is required for
its existing test fixture helpers. No private pane captures are published.
