# Recipient history across reachability changes

The same deferred item retains an external hold while owner reachability changes
owner → lead → owner → lead → owner. Every pass recreates the real
`DeferralAlerter`, retaining only its temporary on-disk ledger. Before the repair,
the unchanged state sends five messages; after the repair, worker and lead each
receive one. Neither revision releases the hold.

Baseline: `dac719b21cfe20131db588a1d8a1c199fb70206d`. Candidate: the commit
containing this reproducer. Source behavior only: synthetic crew cards and fake
transport, with no live crew messages or production writes.

[Readable terminal recording](deferral-recipient-history.output) and
[timing](deferral-recipient-history.timing) are retained here. Inline playback is
not claimed. From the repository root, with the project environment available:

```sh
PYTHONPATH=. python docs/pr-demos/deferral-recipient-history.py
scriptreplay --log-out docs/pr-demos/deferral-recipient-history.output \
  --log-timing docs/pr-demos/deferral-recipient-history.timing
```

The guarded regression also covers old single-recipient ledger migration,
both recipients temporarily unreachable, genuine item-update rearming and failed
owner retry after a successful lead delivery. Migration preserves the receipt
present in the old file; it cannot recover recipients already forgotten by it.
