# Stopped-owner policy comparison

This is an offline library demonstration, not a live unassignment run. Run
`python3 docs/demos/stopped-owner-work.py` from the source checkout. The old
proposal is retained at commit `805a04e`; the current proposal uses the same
synthetic owner evidence and revision-fenced adapter seams.

Watch three differences: P0 has no immediate release; an OPEN item is released
after 3601 measured seconds; IN_PROGRESS remains assigned while administrator
attention persists. No board or live process is accessed. The readable output
is retained in [the transcript](stopped-owner-work.log). This is a transcript,
not a video recording; no terminal video recorder was used. Source acceptance
and operator rollout remain separate; the sweep defaults OFF.
