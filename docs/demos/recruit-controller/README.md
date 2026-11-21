# Existing-controller signed-request preview

The same `st agent spawn --recruitment-request --dry-run --json` input is
rejected by base `ac947ac9febea9e43e6f5e6d8fa488c1fc101414`. Candidate source
`c7e5958a7807e7cb855e9645efb311ed273798d7` verifies the signed fixture and fresh
fixture authorities, then prints a non-executable qualification receipt:
`live: false`, `execution: refused`, `durable_acceptance: false`.

Watch the negative control without `--dry-run`: it refuses before stdin or
key reads. The independent durable fixture then refuses the same nonce twice.
The CLI itself uses memory and makes no durable replay-protection claim.

[Output recording](output.log) and [timing](timing.log) are retained beside this
caption in the repository's existing demo directory. Download both for replay:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

Playback was verified with `scriptreplay`. The output is also the readable
transcript; it is not an inline video. Reproduce from the repository root:

```sh
python3 docs/demos/recruit-controller/run.py
```

The recording names SHA256 hashes of the three executed candidate source
files. Subsequent caption-only changes do not alter those files.

This is a source checkout with explicit synthetic controller identity,
protected key, forge and custody adapters. No real key is loaded or printed,
no service is contacted, no production state is created, and no privileged
operation or live job runs. It proves the controller qualification boundary,
not installed acceptance, transport delivery or production replay protection.
