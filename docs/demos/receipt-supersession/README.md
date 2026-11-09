# Explicit receipt supersession

A native claim can finish before its coordinator records the result. If an
operator subsequently releases that item at a newer revision, the uncertain
receipt still fences ordinary redispatch. The explicit supersession operation
retains that receipt and its uncertainty, sends nothing and authorizes nothing.
A separate fresh dispatch can then create its own receipt. The old receipt
remains unauthorized and cannot be submitted, assigned or replayed.

[Terminal recording](output.log) and [replay timing](timing.log) show the same
isolated file-tracker/terminal-fixture probe on base
`eafa6b46d151aa4338f555eabd1f8d5c3b9a160e` and the implementation accompanying
this demo. This is a replayable terminal log, not a video or live-service proof.
The first run stops after one submission because supersession is unavailable.
The second explicitly supersedes, then authorizes a fresh receipt; two total
submissions are the original plus the fresh request, with no replay.

```sh
python3 docs/demos/receipt-supersession/probe.py
scriptreplay --log-out docs/demos/receipt-supersession/output.log \
  --log-timing docs/demos/receipt-supersession/timing.log
```

The output and timing are retained with this small repository demo. The probe
uses temporary files and a substituted terminal, while calling the real
receipt coordinator and assignment adapter. It changes no live board or pane.
For a real supported recovery, after an independently verified newer native
open/unassigned release, use:

```sh
st go ITEM WORKER --supersede --receipt OLD_RECEIPT --dry-run
# Preview validates the native release; the retained receipt stays fenced.
st go ITEM WORKER --supersede --receipt OLD_RECEIPT
# This returns execution_authorized=false and never sends or claims.
# A separately authorized fresh dispatch remains a separate st go command.
```

`--dry-run` (or `-n`) changes no receipt or tracker state and authorizes no
execution. `--reconcile` remains read-only. Equal/older revisions, an assigned owner,
non-open state, deferral and unreadable native state refuse supersession.
Seeds must also commit a revision-guarded non-empty transition comment for a
same-owner rebind; that SDK correction is a separate change.
