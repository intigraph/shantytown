# Administrator admission demo

A canonical administrator and a worker receive the same isolated gaming hold
and unavailable peer-policy reader. On base `2c880419efcdd25b91dcf49c0aa6c539c8ad631d`,
both refuse. On the candidate source in this PR, the administrator reaches the
stubbed handler and skips the unavailable worker-policy reader; the worker
continues to refuse both. No sessions are started and no credentials are read.
These are source-fixture results, not installed or provider acceptance.

Run `python3 docs/demos/admin-launch/run.py` from this checkout. The identical
probe runs against an archived base package and the current candidate package.
The base archive is temporary; the existing checkout is not changed.

[Readable transcript](transcript.txt). [Terminal recording](recording.txt) and
[timing](timing.txt) are retained here as a small review artifact. Replay after
downloading with `scriptreplay --log-out recording.txt --log-timing timing.txt`.
Playback was checked with util-linux scriptreplay; no inline video is promised.
