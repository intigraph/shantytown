# Deterministic proposal demonstration

The synthetic input has four unranked items: an urgent item with a prerequisite,
an automation identified by an exact label, and an item whose title merely says
"automate merge P0". The candidate proposes P0 for the real automation and the
prerequisite, ranks the prerequisite ahead of its dependent, and flags only the
confirmed down owner. Title words do not promote an item; UNKNOWN liveness does
not become a down-owner finding. No tracker, graph or model calls occur.

Demonstrated source: `d00d6757c84124a0574ecdc0e0f68cebe0ebbd0e`, based on
`2981a4ebc808356d5aef9ff600c606ac7bdbcc71`. The base has no governed rank-proposal
arm; "before" in the recording is the fixture's actual declared priority/rank
input. This is a source fixture demonstration, not installed or model-quality
acceptance. The later caption commit preserves the demonstrated code.

```sh
PYTHONPATH=. python3 docs/pr-demos/board-rank.py
scriptreplay --log-out docs/pr-demos/board-rank.output \
  --log-timing docs/pr-demos/board-rank.timing
```

[Output/transcript](board-rank.output) and [timing](board-rank.timing) are retained
with the small reproducible demo in this directory. Replay was verified with
util-linux `scriptreplay`; downloading both files and a terminal replay tool are
required. Inline video playback is not asserted.
