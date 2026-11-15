# Deferral snapshot recovery demo

Target: an offline library fixture. No server, work item or schedule is invoked.
The board watermark advances during every observation in all three cases.
The unrelated write changes another entity's description; the refusal control
changes a candidate membership predicate on another entity.

Base: `c96be285f052ae5ec709137842240bea0b887ce1`.
Candidate: the implementation in this PR (the recording precedes the final
commit; all demonstrated source bytes are retained in that commit).

Observed output:

```text
BEFORE, unrelated writes: UNKNOWN: no release; query requests=3
AFTER, same unrelated writes: EXACT: demo-held; query requests=7
CONTROL, candidate membership changes: UNKNOWN: no release; query requests=21
```

Repeat from the repository root:

```sh
python3 docs/demos/ebu-snapshot.py
```

[Output recording](ebu-snapshot.output.log) and
[timing recording](ebu-snapshot.timing.log) are small, sanitized terminal
artifacts retained with this PR in the existing demos directory. They require
local download and util-linux playback; inline video playback is not asserted:

```sh
scriptreplay --log-out docs/demos/ebu-snapshot.output.log \
  --log-timing docs/demos/ebu-snapshot.timing.log
```

The source-only fixture demonstrates exactness and bounded recovery, not
installed throughput, absence of future timeouts, or the required 24-hour
scheduled acceptance window.
