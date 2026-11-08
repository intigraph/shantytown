# Owner-first deferral notification

A synthetic P0 wait is ten days overdue, has no setter envelope and retains an
external hold. Watch the recipient change from administrator for every case to
owner, lead or administrator according to reachability. A second unchanged sweep
adds no message; neither revision releases a hold.

This is a real `DeferralAlerter.sweep` call with temporary storage, synthetic crew
cards and a fake transport. It makes no external calls and proves source behavior,
not installed behavior.

- Base: `6bb4694988539c60fbc1a4060a9ecb75fe9c8bcf`.
- Demonstrated source: `7a64a5900bed0415de4ce914660327361b8ffb8c`.
- [Recording output / readable transcript](deferral-owner-routing.output) and
  [timing](deferral-owner-routing.timing), retained in this repository's existing
  demo directory. Download both to replay; inline playback is not claimed.
- [Reproducer](deferral-owner-routing.py), identical input on both revisions.

With the demonstrated source checked out and the project available on
`PYTHONPATH`, run:

```sh
python docs/pr-demos/deferral-owner-routing.py after
```

For the base replay, point `PYTHONPATH` at a clean checkout of the base and run
the same reproducer with `before`. It checks the expected recipient as well as
the unchanged hold and duplicate suppression.

```sh
scriptreplay --log-out deferral-owner-routing.output \
  --log-timing deferral-owner-routing.timing
```

Recording is output-only util-linux `script` format. No live crew messages,
credentials or production state are included.
