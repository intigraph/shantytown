# A busy receiver is checked once per transfer pass

This recorded pure fixture plans five items for one receiver whose actual
`TriageRefused` says it is busy, with an independent ready receiver in the
middle. Before: five calls into the busy receiver. After: one call; all six
outcomes remain visible, and the ready receiver still gets its item, comment
and event. The final control proves that a fresh pass can dispatch to the
previously refused receiver. No real pane or tracker is touched.

Base: `c78cd24f0fd0abee117c97805a1b1f3d5721afa9`. Candidate module blob:
`a8ee3ebae436fcd68c093958ef1d487871ff5842` (the implementation accompanying this demo).

Build no binaries. Run against separate base and candidate source checkouts:

```sh
python3 docs/probes/pr-demos/ceiling-busy/probe.py /path/to/base
python3 docs/probes/pr-demos/ceiling-busy/probe.py /path/to/candidate
```

[Actual output](output.txt) and [timing](timing.log) are a terminal recording;
download both for util-linux playback:

```sh
scriptreplay --log-out output.txt --log-timing timing.log
```

Playback was checked locally. This proves candidate behavior with injected
effects; installed or naturally scheduled acceptance remains separate.
