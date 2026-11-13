# One roster per stop drain

The same isolated event names an agent holding `work-1`. The base drain reads
plates without preparing a roster. The candidate prepares one roster for event
display and administrator workflow; the work remains visible and neither render
reports an unknown plate. The tracker, registry, pane and event fixtures are local;
this recording does not query or change a live deployment.

Run `PYTHONPATH=. python3 docs/demos/stop-roster/demo.py` from a source checkout.
Compare base `4ac66122cb6ab7c9a2233b1f07150303d1645c87` with runtime source commit `dcd9446591971875a5ef8cfd8f401b1fffad4231`.
Later caption-only changes preserve that runtime source and recording.
The actual output is in [output.log](output.log), with [timing.log](timing.log).
Download both and replay with:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

This is a replayable terminal recording with a readable transcript, not an inline
video. Both files are small review artifacts retained with this demo. Production
measurements are separate: per-agent 27 queries + 32 fence GETs = 59 requests in
7.30 seconds; the existing roster primitive used 4 queries + 5 fence GETs = 9
requests in 1.41 seconds. All returned HTTP 200, all 14 plates were known and the
selected-item dictionaries were identical. These serial read-only measurements
qualify the primitive, not installation of this stop-hook wiring or a full hour
of traffic. Freshness fences are preserved.

Runtime follow-up `355159d06c227422a240333655272f5a8f57d975` adds the
hard roster boundary. The stable-roster demo output was revalidated.
The follow-up race control also models an event or registry member arriving after
roster preparation. That owner is reported UNKNOWN without a per-agent read.
The recording above uses a stable roster; late-arrival behavior is covered by
the real-tracker controls in `tests/test_stop_roster.py`.
