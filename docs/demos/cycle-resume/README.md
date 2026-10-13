# Cycle resume demonstration

Trigger: a completed clear followed by a simulated HTTP 408 on the plate read.
The same probe sends **0 → 1 prompts** on base `c711a07` and this PR's source.
The candidate also exposes the plate through both hook channels and reports a
configured 70% context crossing exactly once.

This is a library fixture using `NullPanes`, not an installed Claude session.
It does not establish actual Claude rendering or fleet rollout. The normal
redispatch regression separately controls successful assignment. Fresh transcript
binding is covered by the SessionStart regression (unknown usage stays unknown).

[Readable transcript](transcript.txt), [recorded output](output.log), and
[timing](timing.log) live with this small demonstration in Git. Replay locally:

```sh
scriptreplay --log-out docs/demos/cycle-resume/output.log --log-timing docs/demos/cycle-resume/timing.log
```

Reproduce from the repository root:

```sh
python3 docs/demos/cycle-resume/demo.py c711a07
```

These files are retained with the change; no external hosting or upload is required.

Admission controls in `tests/test_cycle_redispatch.py` use the real dispatcher:
refused work sends zero prompts, admitted work sends one, an allowed HTTP408
recovery sends one, and an HTTP408 under a governor hold sends zero. A governor
refusal is preserved even though the clear itself completed.
