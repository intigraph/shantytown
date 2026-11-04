# Comment error diagnostics

An SDK can print an observe-only identity warning before a comment failure.
On base `2981a4ebc808356d5aef9ff600c606ac7bdbcc71`, the 160-character
prefix hid the terminal error. Candidate
`80f3cdd18559583d0a42905e7b698c26b0e1edf1` shows exit 1 and the
terminal 503. Both make one attempt; the successful-exit control accepts the
observe warning. The later caption commit does not change the demonstrated code.

This is an offline synthetic adapter fixture, not a live service or a diagnosis
of an earlier production failure. No identity check, credential, retry policy or
tracker write is changed by the demonstration.

Reproduce from the repository root:

```sh
PYTHONPATH=. python3 docs/pr-demos/comment-terminal-error.py
```

[Recorded output](comment-terminal-error.output) and
[timing](comment-terminal-error.timing) are retained in this small demo directory
with the reproducer and caption. Replay was verified with util-linux:

```sh
scriptreplay --log-out docs/pr-demos/comment-terminal-error.output \
  --log-timing docs/pr-demos/comment-terminal-error.timing
```

The output is also a readable transcript. This recording requires downloading
both files and a terminal replay tool; inline video playback is not asserted.
