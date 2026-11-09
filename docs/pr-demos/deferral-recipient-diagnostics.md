# Per-recipient deferral diagnostics

An overdue synthetic P0 wait is observed with four recipient states: owner
reachable, only lead reachable, neither reachable, and both sends raising an
exception. Base and candidate choose the same recipients, send no duplicate on
the second pass, retain the deferred status and release nothing. The candidate
adds recipient snapshots and distinguishes `live-absence` from `send-failure`.
The base has only the combined `owner-lead-unreachable` reason for both failures.

This is an isolated source fixture with fake registry/transport and a temporary
state directory. It makes no external calls or real notifications. It proves
source behavior, not installed adoption or later inbox consumption.

Base: `195a7ef3f8683353cfd5ea7b3357e4b1b50950fe`.
Candidate routing source SHA-256 (notify.py followed by deferral_pacing.py):
`111ec2140d0d81e77195b3a2a8bbc1343ddaeaaa24293310b7f5adcd03ec3c9d`.
Both observed source hashes are printed in the recording; the PR pins its head.

From the repository root, repeat:

```sh
sh docs/pr-demos/deferral-recipient-diagnostics.sh
```

The small [output recording](deferral-recipient-diagnostics.output) and
[timing file](deferral-recipient-diagnostics.timing) are retained in the existing
PR-demo directory. The output doubles as a readable transcript. Download both
and replay with util-linux:

```sh
scriptreplay --log-out deferral-recipient-diagnostics.output --log-timing deferral-recipient-diagnostics.timing
```

Playback requires a terminal; no inline video playback is claimed. The recording
was captured with output-only util-linux `script --return`, child exit zero.
