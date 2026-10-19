# Inspect a complete native-memory directory without selecting or uploading it

This source-only recording runs the **same** `st agent memory alpha inspect`
probe on base `708b0348d7ff5dbe140397b95f0b339a4c23a2b4` and implementation
`ebf59214799ab7a57fe1393137258eb0b5f3a68c` with two synthetic UTF-8 files.
Base returns the actual parser refusal (exit 2); the candidate returns complete
2/2 file metadata (exit 0). The index preserves CRLF, the topic includes a
non-ASCII character, and the probe confirms both original bytes and mtimes stay
unchanged. Metadata includes positive target coverage and SHA256 values, with
native selection explicitly `UNCHANGED`.

The [terminal recording](output.log), [timing data](timing.log) and
[readable transcript](transcript.txt) contain actual output, not constructed
success responses. The recording follow-up changes only these demo artifacts.
This is a download-and-replay terminal typescript, not an inline video.

```sh
scriptreplay --log-out docs/demos/versioned-memory/output.log \
  --log-timing docs/demos/versioned-memory/timing.log
```

Repeat from the repository checkout with Python 3.11+ and Git:

```sh
python3 docs/demos/versioned-memory/run.py
```

The reproducer extracts only regular repository source files from the pinned
base into a disposable fixture; it creates no worktree or shared index. It
clears deployment settings for the subprocesses and requires no credentials,
network, service or crew session. Keep this small recording and its exact base
reference with the source so the before/after remains reproducible after merge.
The separate existing `crew-memory` demo continues to exercise the original
read-only Codex startup bridge and is unchanged.

**Limits:** this probe demonstrates the real explicit CLI and complete local
metadata scan. It does not exercise Quipu writes, installed Claude startup or
writeback, an actual crew/harness switch, private migration, lifecycle enablement,
or deployed native round-trip acceptance. The lifecycle tests use attributed
synthetic transports; source approval is not runtime authorization.
