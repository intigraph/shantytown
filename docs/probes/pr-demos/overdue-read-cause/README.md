# Overdue read diagnostics

The same isolated library input raises an HTTP 408 on the base and candidate.
Watch `PartialAnswer` alone become `HTTPError:408` followed by the preserved
UNKNOWN/no-repeat line. Both versions make one stubbed read, send nothing and
preserve pending ledger bytes. The complete-empty control stays quiet.

Recorded source revisions: base `6f573562c55ff62841cb5878d8822a37825a9069`,
candidate `c3ee594a9f273a1215f3b5b673b7de90a1298d15` (the source commit; the recording commit adds only demo files).
This uses actual reader and notifier code with a private transport fixture. It
does not identify the cause of any production failure or demonstrate deployment.

Run from the repository root:

```sh
python3 docs/probes/pr-demos/overdue-read-cause/reproduce.py
```

[Output transcript](output.log) and [timing](timing.log) form a util-linux terminal
recording. Download both into one directory and replay with:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

Inline playback is not provided. These small sanitized artifacts are retained
with the repository's existing PR demo collection.
