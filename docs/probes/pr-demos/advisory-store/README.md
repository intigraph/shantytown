# Selected-store advisory demonstration

The same Seeds-selected request skips on base because the advisory reads a
legacy local store. The candidate proves and reads the selected Seeds store,
then emits a warning from the controlled judgment. Both outcomes are asserted.
All network, store subprocess and model calls are intercepted fixtures; no live
item is created or read and this does not prove installed coverage or precision.

Base: `ee7bf0a2265319967c2a042b149703d8b6346706`. Candidate: the commit containing
this recording, with the selected-store advisory change. Reproduce from the
repository root with `python3 docs/probes/pr-demos/advisory-store/reproduce.py`.
The base commit must be available locally.

[Output recording and readable transcript](output.log) and [timing](timing.log)
are retained with this source. Download both and replay using
`scriptreplay --log-out output.log --log-timing timing.log`; no inline player is
claimed. Recorded output and replay were checked. The small recording shares
this repository's retention policy. Re-record if advisory behavior changes.
