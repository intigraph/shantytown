# Metrics configuration renderer demonstration

Trigger: identical synthetic canonical configuration containing a graph positive
control and the supported metrics URL/password-file pair. Watch the graph control
remain true while the actual Claude renderer changes from omitting both metrics
variables to carrying both.

Base: `4a16b4c1a1d1b3628cf15d007aaf11c414fedfb9`.
Functional candidate: `60e6734f91839497888b1a9d3c04fcb7fc03069a`.
Later demo-only commits preserve these functional source bytes.

Run from the repository root:

```sh
python3 docs/demos/dp-metrics/demo.py
```

The reproducer exports the two committed packages into isolated temporary trees,
then invokes the actual renderer with the same fixture. No credential file,
producer, notification, metrics push or live service is accessed. This is source
behavior, not installed or natural-hook acceptance.

The small output-only terminal recording is retained in this documentation
folder. Download [output.log](output.log) and [timing.log](timing.log), then replay:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

The output log is also the readable transcript. A compatible util-linux
`scriptreplay` is needed; inline playback is not claimed. Raw output and timing
were inspected for private data, and replay was checked. The refreshed recording uses isolated temporary source and HOME directories.
Guarded test results are reported separately in the PR.
