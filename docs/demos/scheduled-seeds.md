# Scheduled seed boundary: native SDK fixture

Base `2ba4862f313ae153d4baf6851d09bd8422d34c57` has no scheduled-seed library
(the original import/help probe exits1: module absent). Candidate module SHA256:
`be03e50ee984e0ff7adc8c331e38cf449169b4ae752def5e9f559dced693003e`. The PR identifies the exact source head.

Set `SCHEDULE_TEST_SD_BIN` to an admitted absolute SDK path and run
`python3 docs/demos/scheduled-seeds.py`. Watch real temporary SDK create/readback
before a **synthetic** go callback, replay without a second create, an actual
local commit whose response is deliberately lost, and exact-ID reconciliation.
The native `workflow_run` link is a canonical run-IRI reference; no signed run
has been published or verified in this fixture. The final success/hold control
makes no pure-code task. Source tests separately prove a failure creates one.

This is a local synthetic project with isolated HOME/CWD/store/identity; no
production graph, real pane or existing credential is used. The assignment seam
returns a controlled result and does not establish normal live go delivery.

Download the [output recording](scheduled-seeds.log) and
[timing](scheduled-seeds.timing), then use
`scriptreplay --log-out scheduled-seeds.log --log-timing scheduled-seeds.timing`.
The small artifacts are retained with the source. Download and terminal replay
are required; no inline video is claimed.
