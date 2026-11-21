# Controller durable preparation

Actual parser on base `abebe316dbffb0aba3688571de1c145e043ad457` refuses the
new preparation selector. Source candidate `f347465a` admits an isolated signed
review fixture through the durable preparation adapter, returns a non-executable
receipt and refuses replay after reopening the store. The source files executed
are unchanged by the subsequent recording-only commit.

Run `python3 docs/demos/recruit-prepare/run.py` from this checkout. Read
[output.log](output.log), or download this directory and run
`scriptreplay --log-timing timing.log --log-out output.log`. Playback was checked.
The small recording stays in this repository alongside its source and caption.

Synthetic enrollment, custody, forge, capability and trusted outer ancestry are
explicit fixtures; the private database and adapter are real. No live listener,
host enrollment, native UID probe, privileged call or job launch is demonstrated.
The explicit preparation mode spends a nonce despite requiring `--dry-run`;
that flag guarantees no launch, not read-only state. Activation remains gated.
