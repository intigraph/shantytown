# Natural idle-cycle receipt

This is an isolated library demonstration, not a live scheduled-cycle receipt.
The base is `165e24e7379d23d76539920cb46bb6a24e6451b4`; the candidate is the commit
containing this directory. The shared inputs are an automatic 500k-context idle
request with a saved checkpoint, a refused request, a manual request and a
successful request carrying a foreign journal unit.

Before: the event is unregistered and every input stays UNKNOWN. After: only the
automatic successful cycle with matching native journal identity returns MET.
Refusal and manual requests emit nothing; foreign journal identity stays UNKNOWN.
MET wakes owner reassessment. Context preservation/reduction and real scheduled
acceptance remain owed.

[Output recording](output.log) and [timing](timing.log) are a replayable terminal
recording, with the output also serving as a readable transcript. Replay with:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

To reproduce, export the base revision to a disposable directory, set
`DEMO_BASE_SOURCE` to that directory, and run from the candidate root:

```sh
python3 docs/demos/natural-idle-cycle/probe.py
```

The probe calls both actual source revisions with synthetic native journal rows.
It never reads a real journal or changes a pane, tracker, request or service.
