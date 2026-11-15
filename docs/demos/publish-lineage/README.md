Publish lineage, offline fixture demonstration

The same `Supersedes: #1` body creates successor #99 on both revisions. On base
`4aa295157989aa734f0adaecdd2283f4408eeb41`, predecessor #1 stays open. On the
candidate, the verified successor is followed by a pointer comment and predecessor
closure. A malformed external reference is refused. All forge operations use
test fixtures: this proves source behavior, not installed or live acceptance.

Run from the repository with pytest installed:

```
python3 docs/demos/publish-lineage/demo.py
```

The retained output/timing pair is a terminal recording, with readable output
as fallback. Replay after downloading both files:

```
scriptreplay --log-out output.log --log-timing timing.log
```

Small sanitized artifacts are retained here with the source. The demonstrated
candidate is the commit containing this directory; later changes must repeat
the probe if its behavior changes. No inline video playback is claimed.
