# Quiet in-progress CI wait

The same in-progress item names one exact CI head. Base `c96be285` emits a
resume while CI is queued. This source candidate emits none until the event is
terminal, then resumes even on failure. The status remains `in_progress` and no
date is written. The CI reader is an isolated fixture; this is source behavior,
not an installed acceptance or merge approval.

Run `python3 docs/demos/quiet-ci-wait/probe.py` with the project's test dependencies.
The probe executes the actual base and candidate stop-hook functions. It asserts
the three observed results and prints the input state alongside delivery.

[Terminal recording](output.log) and [timing](timing.log) are retained in this
small repository demo directory. Replay with
`scriptreplay --log-out docs/demos/quiet-ci-wait/output.log --log-timing docs/demos/quiet-ci-wait/timing.log`.
This is a downloadable terminal recording, with the output log as its readable
transcript; no inline video playback is claimed.
