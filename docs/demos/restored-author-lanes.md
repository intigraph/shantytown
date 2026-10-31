# Restored author lanes, Codex reviews

Run the same read-only admission probe on base
`7420239f03924fa166531e3cc5a8ca1232345041` and the candidate source.
With `admit_class=true`, ordinary, routine, design and important-code authoring
changes from Claude-refused to both harnesses admitted. A legacy-authorized
author stays admitted. Review remains Codex-only even with legacy authorization,
and the frozen control refuses both harnesses in both revisions.

This is a library demonstration with explicit fixture identities. It performs
no dispatch, assignment, HTTP request, live configuration change or installation.
The private dispatch/feed/haul regression tests cover the normal caller paths.

The output-only terminal recording is retained with this source. Download both
files to replay with util-linux `scriptreplay`:

```sh
scriptreplay --log-out restored-author-lanes.log --log-timing restored-author-lanes.timing
```

- [Recording and readable transcript](restored-author-lanes.log)
- [Timing file](restored-author-lanes.timing)
- [Reproducer](restored-author-lanes.py): run
  `python3 docs/demos/restored-author-lanes.py` from the repository root with
  the base commit available locally.

This proves source behavior; installed admission of an actual worker is separate.
