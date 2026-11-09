# Automatic runtime replacement fixture

Base: `195a7ef3f8683353cfd5ea7b3357e4b1b50950fe`.
Candidate runtime implementation: `2c0629ef` (the full revision is in the recording).
The demo/artifact commit changes no runtime implementation.

The same two-session fixture uses running `2.1.319`, installed `2.1.321`, typed
input on one session and background work on the other. The base has no automatic
runtime roller and creates zero requests. The candidate defers both, then saves
a checkpoint and requests one process replacement when input/tasks clear.
A launch alone admits no second replacement; a native-version fixture for a
different session admits the next agent and retains `2.1.319 -> 2.1.321`.

This is a library fixture: versions, pane reads, checkpoint persistence and
credential preflight are synthetic callbacks. It is not installed acceptance,
a live Mac cycle, real credential availability or a network-partition proof.
Base capability detection and candidate execution are shown explicitly.

The output-only terminal recording is [demo.txt](demo.txt) with
[demo.timing](demo.timing). A readable transcript is also in `demo.txt`.
Playback was verified using util-linux `scriptreplay`; download both files and
run:

```sh
scriptreplay --log-out demo.txt --log-timing demo.timing
```

To repeat from a checkout containing the candidate implementation:

```sh
demo_base=$(mktemp -d)
git archive 195a7ef3f8683353cfd5ea7b3357e4b1b50950fe shantytown | tar -x -C "$demo_base"
DEMO_BASE_SOURCE="$demo_base" sh docs/demos/runtime-roll/run.sh
```

These small text artifacts follow the existing `docs/demos` retention convention
and remain in Git with the implementation. No hosted video player is required.
