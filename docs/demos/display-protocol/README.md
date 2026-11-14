# Display protocol fixture

At base `f909de3e`, the display protocol module is absent. This source fixture
shows the candidate's separate display reader accepting a fresh v2 observation,
while the existing live v1 reader rejects it. Expired and decision-eligible
observations remain refused. Transport is mocked; this proves no deployment or
production latency improvement.

Run `python3 docs/demos/display-protocol/run.py` from the source repository.
[Transcript](transcript.txt) and [timing](timing.txt) form an output-only terminal
recording. Replay with `scriptreplay --log-out transcript.txt --log-timing timing.txt`.
No browser embed or network playback is claimed. These small repository-owned
artifacts remain with this source revision. No public host was provisioned.
