# Acknowledge known receipts without listing the whole inbox

The same private named receipt is acknowledged with the original selector at
`e834ef6395e0b4edae094f29515177006d5f5ba5` and the candidate selector. Both avoid
queue enumeration. Watch hydrated `get` calls fall from one to zero: selection
now uses exact receipt metadata, while a separate fresh metadata read still
validates the receipt immediately before its one close. Other messages remain
explicitly unenumerated. Adapters without `inbox_receipts` keep their existing
per-ID compatibility path.

```sh
python3 docs/demos/exact-inbox-selection/reproduce.py
```

The fixture uses in-memory tracker responses, not a live SDK, graph or inbox.
The base commit is printed; the containing PR identifies the candidate commit,
and the module hashes identify the demonstrated code. This shows source call
counts, not installed behavior or measured fleet savings. Refusal, transport,
body-before-close and bounded default-read controls are covered by the tests.

Download [output](output.log) and [timing](timing.log) and replay:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

This small output-only terminal recording uses the existing repository demo
retention convention. It requires downloading and terminal playback; the output
log is also the readable transcript. No inline video playback is claimed.
