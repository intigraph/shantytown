# Codex delivery custody

The same synthetic pane responses replay three inputs: a queued message preview,
a lost Enter, and a human draft. Watch `result`, editing keys and retained state.
The queue changes from reported delivery to unverified custody. A lost Enter
retries once, then clears only the recorded owned text. The human draft receives
no keys on either revision.

Base: `90ff87992594efa46f58d54bb405c2f979749e22`.
Demonstrated implementation: `21d13b51911f4312c6f1cf08400e75d885134311`.
The later recording commit adds demo files only.

This is a replayable terminal recording, with a readable transcript fallback:
[output.log](output.log) and [timing.log](timing.log). Download both and play with:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

Playback was checked with util-linux scriptreplay. No inline video player or
provider session is implied. These small sanitized artifacts are retained here
with the existing repository demos.

From a checkout with pytest available, reproduce both revisions with:

```sh
python docs/demos/codex-delivery/record.py
```

`record.py` exports the exact base into a temporary directory and calls the
identical [probe](probe.py) on both source trees. Dependencies on tmux and the
provider UI are replaced by explicit synthetic responses from the test fixture.
The probe cannot verify an installed provider, an actual notice arrival, or the
supervisor's production schedule. Timed supervisor and block-once event behavior
are exercised separately in `tests/test_delivery_custody.py`.
