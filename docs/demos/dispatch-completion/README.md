# Dispatch receipt completion

A version-named Claude process previously skipped observation. An interrupted
observation left a delivered request at `prepared`, without an authorized
assignment. The same probe now identifies Claude and explicitly completes its
original receipt from retained exact evidence, with one body and one file CAS.
Missing evidence remains fenced; repeated completion sends nothing.

This is a source demonstration: a synthetic terminal adapter supplies retained
submission proof, while the receipt ledger and tracker transition are real.
It does not demonstrate an installed service or exercise a live agent.

Base: `f909de3e3ba445946545dd673f94edea1de2d0fd`.
Demonstrated source: `864c433c02a6557355f72a0d23aa404a18c849a7`.
The subsequent recording commit changes only demo artifacts.

Run from the repository root:

```sh
bash docs/demos/dispatch-completion/run.sh
scriptreplay --log-out docs/demos/dispatch-completion/demo.txt \
  --log-timing docs/demos/dispatch-completion/demo.timing
```

[Output recording and readable transcript](demo.txt), [timing](demo.timing).
Output and timing were recorded with util-linux `script` and replayed with
`scriptreplay`. Download both files to replay in a terminal; no inline player
is assumed. These small sanitized artifacts are retained in this repository.
