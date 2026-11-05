# Resume hook context envelope

The same saved checkpoint is read from an isolated fixture on base `00aeb88`
and implementation `e3b9d29`. The base emits a bracket-prefixed text brief; the
candidate emits valid `SessionStart` JSON with the complete checkpoint and item
and graph pointers. Both consume the brief once and emit nothing on a second
invocation.

This records the actual producer's source output. Plain text is supported by the
official hook contract; bracket-prefix parsing as the cause of the observed
Codex error remains inferred. This is not a native Codex parser test or proof
that an installed relaunch injected the brief.

Read [the actual transcript](output.log), or download it with [timing.log](timing.log)
and replay with util-linux:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

Repeat from the repository root:

```sh
python3 docs/demos/resume-hook-json/demo.py 00aeb88 e3b9d29
```

The small recording and reproducer remain in this repository's existing demo
directory so reviewers need no external artifact service. No inline video
playback is claimed.
