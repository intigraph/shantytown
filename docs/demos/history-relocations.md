# Relocated history publication

Trigger: capture an unchanged or growing session through a private archive
citation symlink, then fully regenerate a relocated scrubbed derivative.
The base replaces the links; the candidate preserves them and updates the
archive. Credential redaction and raw-source preservation stay true in both.

This is a synthetic fixture, not an installed-service demonstration. Base:
`2bd929f8`. Candidate: the source commit containing this recording; the
recorded working tree contains the same capture, scrub and helper implementation.
Repeat with `python3 docs/demos/history-relocations.py` from the repository root.

[Replayable terminal output](history-relocations.log.gz) and
[timing](history-relocations.timing) are retained in this repository with this
fix. Replay after downloading both with
`gzip -dc history-relocations.log.gz > history-relocations.log`, then
`scriptreplay --log-out history-relocations.log --log-timing history-relocations.timing`.
The readable log is the fallback; no inline playback is claimed.
