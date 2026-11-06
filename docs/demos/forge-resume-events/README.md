# Forge event resume conditions

An exact `pr-merged:github/example/project#123` marker was refused on base
`f9941a35a914ec925a8d2226aade3dcb79b124b8`. The candidate accepts it, distinguishes
a merge from an unmerged close, retains UNKNOWN after a failed read, and refuses
a one-hour backstop even with the scheduled-window option. A 24-hour backstop
is accepted.

This is offline source replay against controlled reader fixtures, not a live
forge observation, deferral write, installation or haul acceptance. The runtime
implementation demonstrated is `a8ac4a73c09198d6d30b0b7741f00a5f5ddc07be`;
the commit containing this recording retains those runtime blobs unchanged.
The controller examples also show free prose staying unmet, an exact authorized
grant meeting its gate, spoofed authors staying UNKNOWN, and a newer authorized
revocation retaining the hold.

```sh
python3 docs/demos/forge-resume-events/demo.py
scriptreplay --log-out docs/demos/forge-resume-events/output.txt --log-timing docs/demos/forge-resume-events/timing.txt
```

The small [terminal recording/transcript](output.txt) and [timing](timing.txt)
are retained in this repository with the caption. Playback requires a terminal
with `scriptreplay`; no browser embed is claimed. CI, independent review and
installed owner-deferral acceptance remain separate gates.
