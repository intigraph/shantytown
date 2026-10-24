# Versioned stopped-owner observations

The same library-level stop, with a backwards clock, produces no graph source
on base `71cd44705c1d41cb5ef7a10cc588143da4a0b4b0`. Candidate
`edc6f885ee4acb2ccdf2351bb294f33579238a83` publishes the stopped observation,
deduplicates a repeated stop, advances the head on restart and refuses replay
of an older local revision. Later recording-only commits preserve these product
bytes.

Run `bash docs/demos/stopped-owner-graph/run.sh` from the repository root.
The receiver is synthetic and in memory: this demonstrates source behavior,
not HTTP authentication, installation, native expiry or fleet acceptance.
The temporary base archive is retained for inspection.

[Actual recording](output.log) and [original timing](timing.log) are retained
here as small text artifacts. Download both, then replay with:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

The recording was inspected and replayed locally. It needs a terminal replay
tool; no browser embed is claimed. The script is also the repeatable input.
