# Darwin process posture

A synthetic pane has a shell with a Codex child. BSD `ps` rejects GNU
`etimes`/`--ppid`; BSD `pgrep` also hides the observing caller's ancestors unless
`-a` is used. The same fixture on base `0ed92183` and the candidate produces:

```text
                    base                 candidate
bypass launch       unreadable / MANUAL  readable / bypass
manual launch       unreadable / MANUAL  readable / MANUAL
denied observation  unreadable / MANUAL  unreadable / ?
```

Reproduce against either checkout, with this demo script retained externally:

```sh
PYTHONPATH=/path/to/checkout python3 run.py
```

This is a readable transcript from a synthetic library probe, not a recording
or an installed-runtime acceptance claim. No terminal recorder was available.
The demo collects no live argv or environment. The candidate is the revision
containing this demo; its tests also exercise the Linux command contract and a
real Linux process with a settings pointer beyond a narrow terminal width.
Settings freshness remains a separate observation.
