# Forge event resume conditions

An exact `pr-merged:github/example/project#123` marker was refused on base
`f9941a35a914ec925a8d2226aade3dcb79b124b8`. The candidate accepts it, distinguishes
a merge from an unmerged close, retains UNKNOWN after a failed read, and refuses
a one-hour backstop even with the scheduled-window option. A 24-hour backstop
is accepted.

This is offline source replay against controlled reader fixtures, not a live
forge observation, deferral write, installation or haul acceptance. The runtime
implementation demonstrated is `884b1d8c`; the commit containing this demo retains
those runtime blobs unchanged.

```sh
python3 docs/demos/forge-resume-events/demo.py
scriptreplay --log-out docs/demos/forge-resume-events/output.txt --log-timing docs/demos/forge-resume-events/timing.txt
```

The small [terminal recording/transcript](output.txt) and [timing](timing.txt)
are retained in this repository with the caption. Playback requires a terminal
with `scriptreplay`; no browser embed is claimed. CI, independent review and
installed owner-deferral acceptance remain separate gates.
