# Stats publication pacing

An isolated fixture calls the real `stats.capture` with a fake graph transport.
After the first acknowledged publication, 100 unchanged hooks add 100 remote
reads on baseline `48bb2a84b566cf107214057c4a5e1d05a928080d` and zero on the
candidate containing this recording. Both publish the due heartbeat with four
reads and retain exactly two immutable facts. This demonstrates source behavior;
it does not measure a deployed service or prove an alert has cleared.

From the repository root, with pytest installed:

```sh
python3 docs/pr-demos/stats-publication.py
```

[Output](stats-publication.output) and [timing](stats-publication.timing) are a
small terminal recording retained with this source example. Download both and
replay with util-linux:

```sh
scriptreplay --log-out stats-publication.output --log-timing stats-publication.timing
```

The output is also the readable transcript. Playback requires a terminal and
`scriptreplay`; no inline player is claimed. Separate regression controls cover
partial heads, pending delivery, lost acknowledgments, stop transitions and
explicit remote rollback refusal.
