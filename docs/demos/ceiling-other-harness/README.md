# Ceiling transfer: other harness and active capacity

This is an offline library recording. No tracker, credentials, dispatch or live
ceiling is involved. With the same two eligible receivers, a Claude source moves
to another Claude receiver on base `8ee0f7eaa1bd453838e2a4df69a5eea83673449e`;
the candidate instead selects the Codex receiver. The old holder type has no
harness field, so the script supplies that observed field only to the candidate.

The candidate also counts a fixture with 52 deferred items, one held item and
one active item as one active assignment. A full receiver remains ineligible.
These controls do not count toward policy50's natural operational population.
The recording qualifies source behavior, not installed acceptance or a measured
false-positive rate. The policy effect remains `record`.

Run from the repository root, retaining the pinned base Git object:

```sh
python3 docs/demos/ceiling-other-harness/demo.py
```

[Recorded output](output.log) and [timing](timing.log) can be downloaded and
replayed with util-linux (terminal recording, no inline video player):

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

The original real output and timing are retained beside this caption. The PR
identifies the exact candidate head; the demo's source behavior must be checked
after any source refresh. No natural event is manufactured by this example.
