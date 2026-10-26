# Concurrent cycle receipts

Trigger: two writers reach the rename step together. The base's fixed temporary
name produces one `FileNotFoundError`; the candidate uses private temporary files
and both writes complete. A positive control records a request and its named
refusal. This is a library demonstration using disposable file fixtures, not a
live cycle or an installed acceptance claim.

The [output-only recording](output.log) and [timing](timing.log) use util-linux
`script`; the log is also a readable transcript. Download both to replay:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

Reproduce from the recorded checkout with:

```sh
PYTHONPATH=. python3 docs/demos/cycle-refusal/run.py
```

Base is `bf6869199bdeae416c88284c3e9106abd65a4402`; the recording names the
candidate `cycle.py` SHA256 so later documentation/manifest commits do not imply
a different demonstrated implementation. The script checks that the shared base
JSON helper has not changed. The CLI I/O-failure control is separately exercised
by `tests/test_cycle_request_atomic.py`: the risk list remains visible, a receipt
warning is printed, the command returns REFUSED and no lifecycle call occurs.
The lock does not clear requests, bypass loss guards or retry a refused cycle.

These small source-local recording artifacts remain with this regression.
