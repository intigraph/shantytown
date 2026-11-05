# Incomplete message-read receipts are refused

Trigger: request read marks for two message IDs, while the transport returns a
receipt for only one. The actual adapter on baseline
`a2b2dfc648925aac6450f25fff38c47b8c36f20a` accepts that incomplete response;
this proposal refuses it. Complete typed receipts, including already-read IDs,
remain accepted by the regression controls.

This is an adapter demonstration with an explicitly mocked transport. It opens
no store and sends no request. It demonstrates the incomplete-receipt boundary,
not a production inbox rollout. Candidate source bytes are recorded in
[source-sha256.json](source-sha256.json); the PR links this directory at its
published commit.

Read the [transcript](output.txt), or download the [lossless terminal
recording](output.txt.gz) and [timing](timing.txt), then replay:

```sh
gzip -dc output.txt.gz > output.raw
scriptreplay --log-out output.raw --log-timing timing.txt
```

Replay was verified locally. This is a terminal recording rather than an inline
video. The small files follow the repository's retained PR-demo convention.
To repeat, set `BASE_DIR` and `CANDIDATE_DIR` to the two source checkouts, then
run `bash run-demo.sh` from this directory. No installation or credentials are
required; each invocation uses the selected checkout's real adapter.
