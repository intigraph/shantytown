# Read a declared job, detect a missing identity

The same graph-read CLI request is unsupported on base
`66284bdd8000c785d35a5bb4cc35cd26803bf62c` and succeeds on this candidate
for the known job. Requiring a removed job then exits 2 even though a different
valid declaration remains. Only the HTTP response is synthetic; the command,
reader, validation, output and exit statuses are real. No server write or job
execution occurs. This demonstrates source behavior, not runtime adoption.

[Before/after transcript](quipu-jobs.txt), [candidate recording](quipu-jobs.log)
and [timing](quipu-jobs.timing) are retained beside this caption in Git, following
the existing demos convention. This is a downloadable terminal recording; inline
playback is not promised. Replay was checked with:

```sh
scriptreplay --log-out docs/demos/quipu-jobs.log --log-timing docs/demos/quipu-jobs.timing
```

Repeat the candidate probe with `python3 docs/demos/quipu-jobs.py`. For the base,
export that exact revision into a disposable directory and invoke the same
script with `--source <export-directory>`. The recording applies to the reader
and CLI content in this commit; the base lacks the new flags entirely. A valid
list does not assert executable admission, complete membership without explicit
identity controls, or signed run health. Runtime scheduling remains separate.
