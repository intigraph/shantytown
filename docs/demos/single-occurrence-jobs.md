# Single-occurrence declaration demo

The same integer repeatCount=1 fixture is refused on base
`4b422d9e7d986dd5c87475b058bffad1ed0a5f0a` and decoded as one occurrence
on the candidate. Count=2 remains refused. No installed service is exercised.

Candidate parser SHA256: `890ea850a14d297acfa3e07a0e4f02092880f882274335ed92fd11f3ddfb3c29`.

[Recording](single-occurrence-jobs.log), [timing](single-occurrence-jobs.timing).
Download both and replay with `scriptreplay --log-out single-occurrence-jobs.log --log-timing single-occurrence-jobs.timing`.
The log is also a readable transcript; no inline playback is claimed.

Reproduce using a development environment with pytest:

```sh
git show 4b422d9e7d986dd5c87475b058bffad1ed0a5f0a:shantytown/quipu_jobs.py > /tmp/quipu-jobs-base.py
python docs/demos/single-occurrence-jobs.py --before /tmp/quipu-jobs-base.py
```

The before parser is loaded with current sibling import helpers; the demonstrated
function is pure and performs no transport calls. This is parser behavior, not
schedule, signed execution, graph write or runtime admission. Small sanitized
recording is retained here with the repository's existing demos.
