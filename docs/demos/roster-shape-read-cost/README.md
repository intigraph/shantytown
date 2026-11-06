# Crew roster shape read cost

Trigger: render a frozen 14-worker Seeds roster with one held item per worker.
The real `crew --local --json --no-priority-advice` parser and renderer use an
isolated RDF dataset and pane fixtures. They make no production requests.

The recording first uses the separate shape-admission mode from base
`834b8811c4ceafe8f58d425f384ee902590db369`, then the candidate's fused mode on the
same dataset. The complete rendered JSON rows compare equal. The PR body pins
the exact candidate revision containing these source and fixture blobs.

Observed: **3 query calls → 2**, with **one shape constructor in both modes**.
Capacity for all 14 owners adds no per-owner requests. Total query text is
21,565 → 21,626 bytes; this change removes an HTTP round trip, not guard logic.
Constructor nanoseconds in the recording are individual local samples, not a
benchmark or evidence of lower production connection-held time. The frozen
fixture observes the real serialized HTTP Requests at an in-memory transport
boundary with normal query-only admission; shared-cache hits cannot hide I/O.
Separate projection fence/retry controls cover ordinary cached transport.

[Recording output](output.log) and [original timing](timing.log) are small text
artifacts retained with this demo. Replay after downloading both files:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

This is a terminal recording, not a video or an inline player. Reproduce from
the repository root:

```sh
python3 -m pytest -q -s --disable-warnings tests/test_crew_roster_shape_cost.py
```

The other controls prove that missing, unknown-only, URI and language-tagged
statuses remain UNKNOWN, including a fresh render against a replacement store
identity. No positive observation survives into the next render. The initial
files-backend fixture was rejected as a route mismatch and is not the baseline.
This demo proves source behavior only; no deployment or runtime load recovery
is claimed.
