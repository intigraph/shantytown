# Stopped-owner receipt reconciliation cost

Trigger: one stopped worker delivers a durable pointer while its lead retains
100 closed receipts. The fixture calls the real owned-work tick, tracker and
inbox adapters against a private RDF dataset, observing serialized HTTP requests
at an in-memory transport boundary. It makes no production requests.

Base `6c52e0ba54cca8beb1b9a6a697686f06da4fd6e8` selects **101 receipt subjects**
to confirm the new delivery. Candidate source `1bf1b545` selects **one** receipt
by its returned ID. The recording runs the same fixture on an exact archive of
the base and on the candidate. The baseline's cost assertion intentionally fails;
the candidate passes. Reconciliation still preserves the durable delivery.

[Raw recording](output.log) and [original timing](timing.log) are small text
artifacts. Download both to replay with:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

Reproduce from the repository root:

```sh
python3 docs/demos/receipt-reconciliation-cost/compare.py
```

Additional controls cover a new process recovering a saved ID after a crash,
closed receipts after a lost reply, ambiguous or missing markers, unavailable
legacy readers, and incomplete observations. No uncertain result permits resend.
Unknown-ID recovery adds a bounded identity query before exact metadata; this
change bounds selected and hydrated evidence, not every query's server scan cost.
The full-source suite and live matched-load measurements are separate gates.
No production connection-held-time or installed lifecycle recovery is claimed.
