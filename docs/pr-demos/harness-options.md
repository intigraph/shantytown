# Harness preference round trip

A Claude card with Chrome enabled and an explicit model moves to Codex, then
returns to Claude without a second model argument. Watch command composition
and the restored preference in this isolated card fixture.

Base `7923c5cfc68057406a39c4aee6479f6e509954bf` refuses the Codex command
because Chrome remains enabled; the return conversion also refuses without a
new model. Candidate `74f920d5b2a338a3cbce2ddd8552cf4a7d27b340` composes
Codex without browser flags and restores the saved Claude model and Chrome.
No agent process, credential transition or provider call is performed.

[Terminal output](harness-options.output) · [Timing](harness-options.timing) ·
[Reproducer](harness-options.py). These small artifacts stay in this repository
with the code. Playback was verified with util-linux `scriptreplay`; no inline
video player is claimed.

```bash
python3 docs/pr-demos/harness-options.py
scriptreplay --log-out docs/pr-demos/harness-options.output \
  --log-timing docs/pr-demos/harness-options.timing
```

The recording uses the real committed base package and candidate CLI, file
registry, planner and command composer. Synthetic model identifiers avoid any
provider selection or compatibility claim. Source behavior does not prove an
installed fleet conversion or restored browser tools in a live session.
