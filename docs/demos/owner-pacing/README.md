# Owner reminder ceiling

The same synthetic deferred P0 item is checked at 71 hours, then 73 hours,
then again without changing it. Before the fix, the administrator never sees
the lapsed item. With the fix, the owner gets the first reminder, the
administrator gets one digest after the ceiling, and the duplicate stays quiet.
The item remains deferred throughout.

Baseline: `39f4bf93a956c57a1b7a7ec7f42be3a46cb4a076`. Candidate: the commit
containing this demo. This calls the actual `DeferralAlerter` using synthetic
tracker rows, private temporary state and captured delivery callbacks. It proves
source routing, not a live notification or installation.

Reproduce from the repository root:

```sh
python3 docs/demos/owner-pacing/demo.py --base 39f4bf93a956c57a1b7a7ec7f42be3a46cb4a076
```

The small [terminal recording](output.txt) and [timing file](timing.txt) are
retained beside the reproducer in Git. The output is also a readable transcript;
no inline video playback is claimed. Replay was verified with:

```sh
scriptreplay --log-out docs/demos/owner-pacing/output.txt --log-timing docs/demos/owner-pacing/timing.txt
```
