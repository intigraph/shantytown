# Verified-wake adapter entrypoint demo

Base: `e0a982d8fb74fafe870e2c6ad88c3b6d54b41188`. Candidate implementation is
`shantytown/recruit_adapter.py` blob `9573efc9e793410e4b78468c8d59975f475c4eff`; the PR head retains these
exact demonstrated module bytes. This is a local source demonstration, not an
installed or production controller.

The same routed review input has no entrypoint on base. Candidate shows OFF
refusing before any IO, then isolated fixture readiness/signing/controller
receipt, then mismatched native custody refusing before fixture signing. Watch
the `OFF`, `FIXTURE` and `MISMATCH` lines. Enrollment, readiness, signer and
controller in this short demo are mocks; the separate qualification uses real
loopback HTTP, signatures, test sockets and native controller gates. Neither
starts a real job or reads a production key.

[Readable recording](output.log) and [timing](timing.log) are retained in this
small demo directory. Playback was checked with `scriptreplay`; download both
files and run:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

No inline player is claimed. Reproduce the candidate source contract with
`python3 docs/demos/recruit-adapter/run.py .`; to compare the base, materialize
that base's `shantytown/` package through `git archive`, set `RECRUIT_DEMO_BASE`
to the private extracted directory, and run `bash docs/demos/recruit-adapter/demo.sh`.
The demo records no credentials, payload contents, production endpoint or host.
