# Exact serving commit event (k23b)

Trigger: `installed:quipu@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`.
On base `6c6da5cf96076bfe3e88c01e98a12fb1656735b9`, the parser refuses this full
commit target. The candidate reads the configured loopback fixture's `/version`:
clean exact SHA -> true; same release version with another SHA -> false; dirty
identity -> UNKNOWN. Local CLI metadata cannot satisfy this event.

This is a **source-checkout library demo with an isolated loopback server**,
not installed-service acceptance. Candidate source digest recorded in the actual
transcript: `f73976f0385cc7e83ea203378b84f6aed61bbbc7912f6512f4c3aedbfb0f781e`
for `shantytown/resume_kinds.py`. The paired tests also store the marker through
Dispatcher and evaluate it through the real deferral reader.

Reproduce from the checkout with `python3 docs/demos/installed-serving-sha/demo.py`.
The standard-library demo needs the retained base commit in Git history and never
queries production, changes a real tracker, or prints credentials.

Replay the output-only terminal recording:

```sh
scriptreplay --log-out docs/demos/installed-serving-sha/output.log --log-timing docs/demos/installed-serving-sha/timing.log
```

[Readable transcript](output.log), [timing file](timing.log), [reproducer](demo.py).
The small recording is retained in this repository with the source. Playback uses
util-linux `scriptreplay`; no inline video playback is promised.
