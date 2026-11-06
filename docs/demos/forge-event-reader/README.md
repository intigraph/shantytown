# Forge event reader before and after

This is an offline library demonstration. The same synthetic Forgejo responses
are evaluated by base `a2afbdf4660908757245f349b826d5707c6e22f9` and the candidate
reader in this checkout. No forge, tracker, credential or installed service is
accessed.

Watch two changes: a native `trigger_event` with an empty legacy `event` goes
from UNKNOWN to a terminal wake condition; a pending status on page two goes
from incorrectly terminal to known active. The second case is a refusal control:
a pending context must never wake a terminal-CI wait.

Run from the repository root:

```sh
python3 docs/demos/forge-event-reader/demo.py
```

[Readable transcript](transcript.txt). The output-only terminal recording is
[output.log](output.log), with [timing.log](timing.log). Download both and replay:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

The candidate is the reader source in the commit containing these files. The
small recording and transcript are retained here with that source. This proves
fixture behavior, not installation, scheduled consumption or a green CI result.
Fair rotation, unchanged phase caps and retry accounting have separate regression
tests; a terminal event is never review or merge permission.
