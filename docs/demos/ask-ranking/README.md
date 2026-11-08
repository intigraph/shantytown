# ASK decisions in priority comparisons

An unlabelled `ASK Stiwi` P1 item must not tell a worker doing P2 work to
switch tasks. The same fixture with real unowned P1 work must still advise it.

[Terminal recording](recording.txt) · [timing](timing.txt) · [reproducer](run.py).
Download both recording files and replay with:

```sh
scriptreplay --log-out recording.txt --log-timing timing.txt
```

The actual library calls show the ASK advisory changing from `True` to `False`;
the real-work control stays `True` on both sides. This is an isolated synthetic
digest, not a running fleet or deployment. The base predicate is loaded from
commit `5e5057dde583169d611d02956d80604c3c9cef88`; the candidate predicate file
has SHA256 `4f66edb251c0723dce3ce211f134276e3ef91fc9924f2bc01d2c153c0da18fc0`.
The PR identifies the candidate commit containing these bytes. Both predicates
are passed to the same real digest implementation, with no tracker writes.

From the repository root, reproduce with `PYTHONPATH=. python3
docs/demos/ask-ranking/run.py`. The small recording and timing files stay in
this demo directory with the source; replay requires util-linux scriptreplay.
