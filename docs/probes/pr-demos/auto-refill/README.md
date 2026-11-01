# Automatic refill and owned-composer recovery

This is a recorded local library fixture, with no live panes or network writes.
The twelve-line warning-footer notice reads `no-box` on base
`a5275a8eeab21da36a30ac2e292c119890dc7878` and `queued` on candidate
`23d5869d86f00fd79e1ffc29bd0053d89400b1c7`. Then one automatic tick moves an
unassigned task from `open` to `in_progress`, owned by the idle author, using
the actual `Dispatcher.go` with a disposable file tracker and `NullPanes`.

Watch the two classifier results and the task owner after the tick. The fixture
supplies observed idle capacity; it does not demonstrate a deployed census,
production governance admission or the required 24-hour scheduled acceptance.

Replay the [recording](recording.log) with its [timing file](recording.time):

```sh
scriptreplay --log-out docs/probes/pr-demos/auto-refill/recording.log \
  --log-timing docs/probes/pr-demos/auto-refill/recording.time
```

Download both files or run from a checkout. Terminal replay was verified; no
browser embed is claimed. CR line endings were normalized to LF with the same
chunk delays and adjusted byte counts. The log is also a readable transcript.
These small evidence files remain in this existing repository demo directory.

Reproduce using the project's declared test environment:

```sh
python docs/probes/pr-demos/auto-refill/demo.py a5275a8
```

The matching regression controls cover blocked plates, an existing owned queue,
holds, uncertain sends, foreign drafts, session changes, slow snapshots and a
slow worker that must not starve later members. See `tests/test_refill.py` and
`tests/test_stale_notice_recovery.py`.
