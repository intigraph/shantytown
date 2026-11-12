# Advisory overlap creation

The same synthetic forge input refused creation on base
`41bbe614d12057b582f70314cbb2e37fe2bff9dc` with zero POSTs. Candidate source
creates one draft for an ordinary overlap and includes the PR/head/files in its
body. Release automation is excluded and creates normally. A duplicate branch
still refuses with zero POSTs. Neither run contacts a forge.

Run from the checkout: `PYTHONPATH=. python3 docs/probes/advisory-overlaps/demo.py`.
The candidate is the source revision containing this probe; its parent baseline
is pinned above. This demonstrates library behavior, not installed acceptance.

[Recording](recording.log), [timing](timing.log). Download both and replay with
`scriptreplay --log-out recording.log --log-timing timing.log`. This is a terminal
recording with a readable transcript, not an inline video. These small sanitized
artifacts are retained in the repository alongside the repeatable probe.
