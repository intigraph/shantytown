# Private scratch in PR preflight

Run `python3 docs/demos/private-scratch-preflight.py` from this checkout with
base `4e6500e808c49422987311f221d00cc54339f9e8` available locally. The offline
reproducer uses actual temporary Git repositories and a synthetic API. It never
creates a live PR or changes an existing private workspace.

Before, untracked top-level `.work/` and `.task-notes/` refuse a committed,
published candidate. After, both are admitted without reading their contents or
including them in the proposed source files or PR metadata. Tracked dirt and a
symlink replacing the scratch directory still refuse. The demo checks synthetic
private bytes, modes and Git status remain unchanged.

Download the recording and timing file, then replay:

```sh
scriptreplay --log-out private-scratch-preflight.log --log-timing private-scratch-preflight.timing
```

- [Recording and transcript](private-scratch-preflight.log)
- [Timing](private-scratch-preflight.timing)
- [Reproducer](private-scratch-preflight.py)

This is source behavior. Installed normal preflight acceptance is separate.
