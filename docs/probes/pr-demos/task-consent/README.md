# Task consent delivery boundary

Synthetic local workspace, baseline `b4d5a1fa` versus this candidate. The same
provisioning call emits consent bytes. Before: no job hash, so folder trust
refuses. After: the emitted bytes are bound to the task; a later edit still
refuses. This demonstrates the library boundary, not a live agent launch.

Run from the repository root with Python 3.11 or later:

```sh
python3 docs/probes/pr-demos/task-consent/demo.py
scriptreplay --log-out docs/probes/pr-demos/task-consent/output.log --log-timing docs/probes/pr-demos/task-consent/timing.log
```

The small output-only recording and timing file are retained here with the
reproducer, following the existing `docs/probes/pr-demos` convention. Playback
requires downloading both files and `scriptreplay`; no inline player is assumed.
