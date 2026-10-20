# Acknowledge known receipts without listing the whole inbox

The same private receipt is acknowledged using the base CLI function and the
candidate. Watch `enumerate` fall from one to zero; exact GETs rise from one to
two, and the intended close remains one. The second GET still validates the
receipt immediately before closing. Other messages are explicitly unenumerated.

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
