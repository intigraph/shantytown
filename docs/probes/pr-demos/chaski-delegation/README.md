# Chaski delegation: local evaluator cutover

The same enabled, due TOML job produces **one local delivery attempt on base
7923c5cf, zero with explicit Chaski delegation on the candidate**, and one with
the candidate's local-scheduler control. The fixture uses the real TOML runner,
cursor and ledger with an offline delivery callback. It executes the exact base
`_jobs_sweep` extracted from Git and the candidate's imported implementation.
It is not an installed tend pass, Chaski firing or migration acceptance.

Run from the repository root:

```sh
PYTHONPATH=. python3 docs/probes/pr-demos/chaski-delegation/demo.py
```

The fixture owns temporary directories and never calls a tracker, pane or
network service. The regression suite separately checks that the entire tend
evaluator is skipped and manual local execution/eligibility checks refuse after delegation.

The readable transcript is `output.txt`; the lossless terminal recording is
`output.txt.gz` with `timing.txt`. Download the two recording files and replay:

```sh
gzip -dc output.txt.gz > recording.txt
scriptreplay --log-out recording.txt --log-timing timing.txt
```

Terminal replay is verified; no inline video playback is claimed. The source
hash manifest binds the recorded implementation and fixture.
