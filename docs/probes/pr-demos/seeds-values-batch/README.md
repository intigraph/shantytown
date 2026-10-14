# Native Seeds batch-read demo

This is a terminal recording of a disposable loopback Quipu 0.13.0 fixture
(source revision `ec3b707dc2976e579e634f276e752c7715a9ac99`). It creates 80
synthetic work items, checks the same 13 held plates, and reads 67 ready and
12 active items. No production store is used.

The proposed reader uses **5 query calls for the 13 plates** and **4 for the
complete queue**. A separate native control disabling roster preparation reads
the same 13 plates correctly but fails the query-budget assertion at **40
calls**. The recording shows the proposed reader, not that separate control.
Deletion followed by a new reader verifies that a render cannot retain a
previous assignment indefinitely.

[Recorded output](output.log.gz) and [timing data](timing.log) are retained here as
small, sanitized review artifacts. Playback was checked with `scriptreplay`:

```sh
gzip -dc output.log.gz > output.log
scriptreplay --log-out output.log --log-timing timing.log
```

To reproduce, set `SHANTYTOWN_TEST_QUIPU_SERVER` to a checksummed local
`quipu-server` executable, then run:

```sh
python -m pytest -qs tests/test_seeds_plate_batch_native.py
```

Without that explicit executable the optional native test skips. The ordinary
suite separately checks UNKNOWN on unavailable/malformed reads, scope escape,
identity ambiguity, and refusal to fall back to SDK hydration.

The source starts from `5bbb240404c6a6e8383f9ee07fda691521103d4c`. This recording
covers the proposed batch readers in this PR. It does **not** establish live
hook counts, installed adoption, runtime latency, or a whole-hour request rate.
Those use the original read-only wire probes and natural deployment evidence.
