# Composer observation evidence

The same ambiguous offline capture still reports UNKNOWN. The new read-only
wrapper adds a bounded reason, observation time, duration, package version and
classifier digest. A timeout stays UNKNOWN with `capture-timeout`; exception and
composer text are omitted. This adds evidence, not a parser or incident-cause fix.

Base classifier: `2300f4d594b4c711f59433a8de2246a1cd6b1cf2`; the classifier is
unchanged by this proposal. Candidate is the PR head's `input_observation.py`.
The PR body identifies the exact source commit. Wall/monotonic clocks and capture
are fixture callbacks. These are source-library observations, not deployed state.

Repeat from the repository with Python 3.11+: `PYTHONPATH=. python3
docs/probes/input-observation/demo.py` (one line).

[Real output](output.txt) and [timing](timing.txt) are a small output-only terminal
recording retained beside this caption. Download both and replay with
`scriptreplay --log-out output.txt --log-timing timing.txt`; terminal playback
was verified. No inline player or live pane is required.
