# Refill collection with large retained notes

The offline wire fixture has one active item with 65,537 bytes of retained notes
and one future-parked item. The same actual collector regression runs first with
`SdTracker.active_rows` from baseline `2e85dd1431ff41ab2d320b0e00c97eaa3682ae02`,
then with the candidate method. It uses mocked query responses, not a production
store or a scheduled tick.

Before, the collector reports `PartialAnswer` and writes no observation. After,
it writes an observation, excludes the parked item, and still refuses oversized
notes when a quiet-wait reader explicitly requests them. No share or note cap
changes. Installed recovery needs two new natural observations read with a gap.

Run `python3 docs/demos/refill-unused-notes/demo.py` from the repository root.
The small recording and timing file are retained here with the source:

- [Terminal output](output.log)
- [Replay timing](timing.log)

Download both and replay with
`scriptreplay --log-out output.log --log-timing timing.log`.
Playback requires a local terminal; no inline playback is claimed.
