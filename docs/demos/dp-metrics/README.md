# Metrics configuration renderer demonstration

Trigger: identical synthetic canonical configuration containing a graph positive
control and the supported metrics URL/password-file pair. Watch the graph control
remain true while the actual Claude renderer changes from omitting both metrics
variables to carrying both.

Base: `708b0348d7ff5dbe140397b95f0b339a4c23a2b4`.
Functional candidate: `b6b299ed146f1b58aa3f45281aa997aaad76bce9`.
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
were inspected for private data, and replay was checked. The guarded recording
run left watched HOME paths and UID resources unchanged.
