# Owned fixture coverage demo

Trigger: a sanctioned temporary suite contains a public-remote test repository
while an ordinary public repository exists beside it. On base
`57092b9918437ad9278d83b71ce74e8cc4c99647`, both count toward fleet coverage.
The candidate reports **2 public/2 armed -> 1 public/1 armed + 1 owned fixture**.
No production sweep or service change is demonstrated.

The candidate installer bytes have SHA256 `7c357066dc1964f5084e6fed26758eac4d2f83a1e35365d91bbf629f099ac97d`. The recording is from
the source in this PR; future byte changes require a renewed demonstration.
Both invocations use the same isolated two-repository input and explicit root,
private config, neutral-source directory and metric file. The separate selftest
also retains shared-worktree, physical and relative core.hooksPath overrides, symlink,
lookalike and unknown-custody controls.

[Output recording](output.log) and [timing](timing.log) replay locally with:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

This is a terminal recording, not an inline video. Repeat the demonstration:

```sh
python3 docs/demos/owned-fixture-coverage/demo.py
```

The raw output is also the readable transcript. Artifacts live alongside the
existing repository demos and remain in Git history. Complete CI, independent
binding, normal propagation and an observed scheduled run remain separate.
