# Busy status above queued inputs

A current Working spinner ten or twenty rows above the composer used to read
idle in both the triage and input-editing guards. The same fixtures now read
busy; corresponding idle queues remain idle. Queue previews are excluded from
chrome measurements, including any Working text quoted inside the preview.

The [recorded output](output.log) and [timing](timing.log) compare baseline
`6906320da6e0b36a27cddacccafb37a9fbb42cd1` with the source change accompanying
this recording. This uses synthetic, sanitized queue geometry, not a live pane.
It demonstrates source behavior; installed delivery acceptance is separate.

```sh
export BUSY_QUEUE_BASELINE=/path/to/baseline-source
python3 docs/demos/6wr-busy-queue/reproduce.py
scriptreplay --log-out docs/demos/6wr-busy-queue/output.log \
  --log-timing docs/demos/6wr-busy-queue/timing.log
```

The small terminal recording is retained beside the existing repository demos.
It requires downloading and `scriptreplay`; no inline video playback is claimed.


The review repair also preserves current status after a quoted queue heading.
`queue-boundary.py` compares reviewed head `076e0d95` with the repair using
`QUEUE_BOUNDARY_BASELINE=/path/to/reviewed-source`. The private NullPanes
fixture changes from false idle with three editing controls to busy with zero
controls. Replay `boundary-output.log` with `boundary-timing.log`; this uses no
live pane or keystrokes.
