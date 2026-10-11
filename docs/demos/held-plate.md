# Held plate lookup

A synthetic tracker contains one current task and 200 unread notifications.
Both revisions select `held`. Base faca10f loads 201 owner rows and checks 200
ready rows; the candidate reads zero hooked rows and one in-progress row, and
never reads the open queue or readiness. The fixture replaces only CLI transport;
plate selection and status filtering use the real Shantytown reader.

[Recording](held-plate.cast) (asciinema v2; download and run `asciinema play held-plate.cast`)
and [actual transcript](held-plate.txt). The recording contains the two actual
fixture outputs; inline playback is not asserted. Reproduce with
`python3 docs/demos/held-plate.py` on each revision.

A separate read-only live anchor probe selected the same held item on both
revisions while `/query` requests fell from 108 to 13 (88%). This is candidate
behavior, not an installed or fleet-wide reduction claim. Private traces remain
with the task evidence; the synthetic recording contains no operational data.
