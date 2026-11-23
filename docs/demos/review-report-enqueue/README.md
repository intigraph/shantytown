# Signed review report to enqueue Action

Two deliveries of the same protected, signed APPROVE report pass through the
mailbox reaper, signature verification and durable custody. Watch the private
adapter call count remain one and its intent become queued.

Baseline `e0a982d8fb74fafe870e2c6ad88c3b6d54b41188`: the same positive control fails because no adapter
call file exists. Candidate: one adapter process invocation for two reports.
The recording was made from this PR's source; the exact test, implementation and
recording bytes are committed together. The caption does not claim installation.

Run with the existing test extras:

```sh
python3 -m pytest -q -s --disable-warnings tests/test_review_report_enqueue.py::test_approve_report_enqueues_exactly_once_through_reaper
scriptreplay --log-out docs/demos/review-report-enqueue/output.txt --log-timing docs/demos/review-report-enqueue/timing.txt
```

[Output recording](output.txt) and [timing](timing.txt) are a small output-only
PTY recording retained here in Git. Playback requires downloading both files
and util-linux scriptreplay; no inline playback is claimed.

The test uses a private signed RDF/key fixture and a local adapter process.
Job UID and immutable outer ancestry are modelled; signatures, custody/fsync
and adapter invocation are real production code. It enqueues no real PR,
launches no job, and proves neither native forge admission nor runtime activation.
The production flag remains false by default; a separately installed native
adapter must enforce all current admission gates before activation.
