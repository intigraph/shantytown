# Reminder digest transcript

[Actual candidate transcript](transcript.json): an isolated exact reader returns
112 overdue work items for one recipient. The delivery sink receives one digest
on the first pass and none on the next. The source base a9a01367be07206a055ee562764e7f882242ef80 has no overdue reminder sweep; this transcript demonstrates
only the added candidate path, not a before/after production delivery claim.

This is a readable transcript; no terminal recorder executable was available.
`python3 docs/probes/pr-demos/overdue-reminders/reproduce.py` repeats the transcript.
`python3 -m pytest -q tests/test_overdue.py` reproduces the digest and positive
controls, including cooldown, ambiguous write reconciliation and shared unlock
replay. The live schedule and actual recipient arrival remain separate acceptance.
