# Interrupted stop-drain enrichment

The same simulated hook deadline interrupts the actual base and candidate drain
while it reads tracker metadata. Before, the report is marked delivered with no
model response and the next drain is silent. After, the report remains pending;
the next drain emits it, and a third drain is silent.

Base: `c666ed268a277d57b0db63cf12b789d42cbe984d`. Candidate implementation blob:
`2d49b716e8ffe680f6b969c19d9b955076e3ae59`, in the PR head containing this demo.
From the repository root:

```sh
python3 docs/pr-demos/drain-interrupted-enrichment.py c666ed268a277d57b0db63cf12b789d42cbe984d
scriptreplay --log-out docs/pr-demos/drain-interrupted-enrichment.typescript --log-timing docs/pr-demos/drain-interrupted-enrichment.timing
```

[Recording](drain-interrupted-enrichment.typescript) and
[timing](drain-interrupted-enrichment.timing) require downloading and terminal
replay; [plain transcript](drain-interrupted-enrichment.txt) is readable directly.
Retain these small, sanitized artifacts with this change in the existing demo
directory. This uses an in-memory event store and a simulated deadline, and
proves source behavior rather than installed delivery or durable model acknowledgement.
