# Capacity field-read demonstration

The same source fixture stages a deferral deadline and then a deferred status.
The real capacity guard observes the fixture owner before and inside its lock.
Tracker transport and final writes are mocked; HOME is an isolated temporary
directory. No SDK process, graph or installed service is involved.

Base `33345efa26f8beb162c673c4e5c5801217c09544` makes four rich `get` calls. Source head
`d4e7d280d35b2e169df040456469244fe2cc08af` makes four bounded field-read calls and zero rich
calls, retaining the same two writes. Later recording/documentation commits
retain those production source blobs unchanged.

[Readable recording output](output.log) and [timing file](timing.log) form a
replayable util-linux terminal recording. Download both files and play them with:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

The recording was replay-checked locally; no inline video player is claimed.
Repeat the guard-only fixture from a checkout with both commits available:

```sh
python3 docs/demos/2mqg-capacity/read-counts.py --base 33345efa26f8beb162c673c4e5c5801217c09544 --head d4e7d280d35b2e169df040456469244fe2cc08af
```

These small text artifacts remain versioned with the repository. This demonstrates
which reader the guard calls. It does not measure end-to-end defer latency,
transport byte savings or installed acceptance; the matched workflow replay is
separate.
