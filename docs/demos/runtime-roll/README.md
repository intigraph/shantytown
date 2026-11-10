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


## Peer-ledger failure repair

The same two-host fixture injects a failure on the first version-ledger write.
At exact prior head `677c4e238f439c085f1611202031bff62eda763c`, the first
request remains pending while its published row says current; the second host
also admits a request (two pending hosts). Candidate runtime revision
`28beeb4eca2ff46102eb1caaf66544f6a5d620f2` persists the reservation first:
the same failure creates no first request and only the second host admits.
A second candidate control fails the final write after request commit; the
published reservation remains requested and blocks the second host.

[Recorded output](peer-ledger.txt) and [timing](peer-ledger.timing) are retained
here. Playback with `scriptreplay --log-out peer-ledger.txt --log-timing
peer-ledger.timing` was verified. Repeat by extracting the prior head's
`shantytown` directory into an isolated directory, setting `DEMO_BASE_SOURCE`
to it, and running `sh docs/demos/runtime-roll/peer-ledger-run.sh`.
This is a synthetic local library fixture, not deployed fleet acceptance or a
proof against simultaneous peer censuses during a network partition.
